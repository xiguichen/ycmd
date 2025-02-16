# Copyright (C) 2015-2021 ycmd contributors
#
# This file is part of ycmd.
#
# ycmd is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# ycmd is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with ycmd.  If not, see <http://www.gnu.org/licenses/>.

from hamcrest import ( assert_that,
                       contains_exactly,
                       contains_inanyorder,
                       empty,
                       equal_to,
                       has_entries,
                       has_entry,
                       matches_regexp )
from unittest.mock import patch
from unittest import TestCase
from pprint import pformat
import itertools
import os
import requests

from ycmd import handlers
from ycmd.tests.rust import setUpModule, tearDownModule # noqa
from ycmd.tests.rust import PathToTestFile, SharedYcmd
from ycmd.tests.test_utils import ( BuildRequest,
                                    ChunkMatcher,
                                    ErrorMatcher,
                                    ExpectedFailure,
                                    LocationMatcher,
                                    WithRetry )
from ycmd.utils import ReadFile


RESPONSE_TIMEOUT = 5


def RunTest( app, test, contents = None ):
  if not contents:
    contents = ReadFile( test[ 'request' ][ 'filepath' ] )

  def CombineRequest( request, data ):
    kw = request
    request.update( data )
    return BuildRequest( **kw )

  # Because we aren't testing this command, we *always* ignore errors. This
  # is mainly because we (may) want to test scenarios where the completer
  # throws an exception and the easiest way to do that is to throw from
  # within the FlagsForFile function.
  app.post_json( '/event_notification',
                 CombineRequest( test[ 'request' ], {
                                 'event_name': 'FileReadyToParse',
                                 'contents': contents,
                                 'filetype': 'rust',
                                 } ),
                 expect_errors = True )

  # We also ignore errors here, but then we check the response code
  # ourself. This is to allow testing of requests returning errors.
  response = app.post_json(
    '/run_completer_command',
    CombineRequest( test[ 'request' ], {
      'completer_target': 'filetype_default',
      'contents': contents,
      'filetype': 'rust',
      'command_arguments': ( [ test[ 'request' ][ 'command' ] ]
                             + test[ 'request' ].get( 'arguments', [] ) )
    } ),
    expect_errors = True
  )

  print( f'completer response: { pformat( response.json ) }' )

  assert_that( response.status_code,
               equal_to( test[ 'expect' ][ 'response' ] ) )
  assert_that( response.json, test[ 'expect' ][ 'data' ] )


def RunGoToTest( app, command, test ):
  folder = PathToTestFile( 'common', 'src' )
  filepath = os.path.join( folder, test[ 'req' ][ 0 ] )
  request = {
    'command': command,
    'line_num': test[ 'req' ][ 1 ],
    'column_num': test[ 'req' ][ 2 ],
    'filepath': filepath,
  }

  response = test[ 'res' ]

  if isinstance( response, list ):
    expect = {
      'response': requests.codes.ok,
      'data': contains_inanyorder( *[
        LocationMatcher(
          os.path.join( folder, location[ 0 ] ),
          location[ 1 ],
          location[ 2 ]
        ) for location in response
      ] )
    }
  elif isinstance( response, tuple ):
    expect = {
      'response': requests.codes.ok,
      'data': LocationMatcher(
        os.path.join( folder, response[ 0 ] ),
        response[ 1 ],
        response[ 2 ]
      )
    }
  else:
    error_type = test.get( 'exc', RuntimeError )
    expect = {
      'response': requests.codes.internal_server_error,
      'data': ErrorMatcher( error_type, test[ 'res' ] )
    }

  RunTest( app, {
    'request': request,
    'expect' : expect
  } )


class SubcommandsTest( TestCase ):
  @SharedYcmd
  def test_Subcommands_DefinedSubcommands( self, app ):
    subcommands_data = BuildRequest( completer_target = 'rust' )

    assert_that( app.post_json( '/defined_subcommands', subcommands_data ).json,
                 contains_inanyorder( 'FixIt',
                                      'Format',
                                      'GetDoc',
                                      'GetType',
                                      'GoTo',
                                      'GoToDeclaration',
                                      'GoToDefinition',
                                      'GoToDocumentOutline',
                                      'GoToImplementation',
                                      'GoToReferences',
                                      'GoToSymbol',
                                      'GoToType',
                                      'RefactorRename',
                                      'RestartServer' ) )


  @SharedYcmd
  def test_Subcommands_ServerNotInitialized( self, app ):
    filepath = PathToTestFile( 'common', 'src', 'main.rs' )

    completer = handlers._server_state.GetFiletypeCompleter( [ 'rust' ] )

    @patch.object( completer, '_ServerIsInitialized', return_value = False )
    def Test( app, cmd, arguments, *args ):
      RunTest( app, {
        'description': 'Subcommand ' + cmd + ' handles server not ready',
        'request': {
          'command': cmd,
          'line_num': 1,
          'column_num': 1,
          'filepath': filepath,
          'arguments': arguments,
        },
        'expect': {
          'response': requests.codes.internal_server_error,
          'data': ErrorMatcher( RuntimeError,
                                'Server is initializing. Please wait.' ),
        }
      } )

    Test( app, 'Format', [] )
    Test( app, 'FixIt', [] )
    Test( app, 'GetType', [] )
    Test( app, 'GetDoc', [] )
    Test( app, 'GoTo', [] )
    Test( app, 'GoToDeclaration', [] )
    Test( app, 'GoToDefinition', [] )
    Test( app, 'GoToImplementation', [] )
    Test( app, 'GoToReferences', [] )
    Test( app, 'RefactorRename', [ 'test' ] )


  @WithRetry()
  @SharedYcmd
  def test_Subcommands_Format_WholeFile( self, app ):
    filepath = PathToTestFile( 'common', 'src', 'main.rs' )

    RunTest( app, {
      'description': 'Formatting is applied on the whole file',
      'request': {
        'command': 'Format',
        'filepath': filepath,
        'options': {
          'tab_size': 2,
          'insert_spaces': True
        }
      },
      'expect': {
        'response': requests.codes.ok,
        'data': has_entries( {
          'fixits': contains_exactly( has_entries( {
            'chunks': contains_exactly(
              ChunkMatcher( "",
                            LocationMatcher( filepath, 17,  4 ),
                            LocationMatcher( filepath, 17, 16 ) ),
              ChunkMatcher( "",
                            LocationMatcher( filepath, 18,  1 ),
                            LocationMatcher( filepath, 19,  1 ) ),
              ChunkMatcher( "",
                            LocationMatcher( filepath, 19,  8 ),
                            LocationMatcher( filepath, 20,  8 ) ),
              ChunkMatcher( "",
                            LocationMatcher( filepath, 20, 10 ),
                            LocationMatcher( filepath, 20, 11 ) ),
              ChunkMatcher( "",
                            LocationMatcher( filepath, 20, 13 ),
                            LocationMatcher( filepath, 21,  1 ) ),
            )
          } ) )
        } )
      }
    } )


  @ExpectedFailure(
    'rangeFormat is not yet implemented',
    matches_regexp( '\nExpected: <200>\n     but: was <500>\n' ) )
  @SharedYcmd
  def test_Subcommands_Format_Range( self, app ):
    filepath = PathToTestFile( 'common', 'src', 'main.rs' )

    RunTest( app, {
      'description': 'Formatting is applied on some part of the file',
      'request': {
        'command': 'Format',
        'filepath': filepath,
        'range': {
          'start': {
            'line_num': 17,
            'column_num': 1,
          },
          'end': {
            'line_num': 22,
            'column_num': 2
          }
        },
        'options': {
          'tab_size': 4,
          'insert_spaces': False
        }
      },
      'expect': {
        'response': requests.codes.ok,
        'data': has_entries( {
          'fixits': contains_exactly( has_entries( {
            'chunks': contains_exactly(
              ChunkMatcher( 'fn format_test() {\n'
                            '\tlet a: i32 = 5;\n',
                            LocationMatcher( filepath, 17, 1 ),
                            LocationMatcher( filepath, 22, 1 ) ),
            )
          } ) )
        } )
      }
    } )


  @SharedYcmd
  def test_Subcommands_GetDoc_NoDocumentation( self, app ):
    RunTest( app, {
      'description': 'GetDoc on a function with no documentation '
                     'raises an error',
      'request': {
        'command': 'GetDoc',
        'line_num': 3,
        'column_num': 11,
        'filepath': PathToTestFile( 'common', 'src', 'test.rs' ),
      },
      'expect': {
        'response': requests.codes.internal_server_error,
        'data': ErrorMatcher( RuntimeError,
                              'No documentation available.' )
      }
    } )


  @WithRetry()
  @SharedYcmd
  def test_Subcommands_GetDoc_Function( self, app ):
    RunTest( app, {
      'description': 'GetDoc on a function returns its documentation',
      'request': {
        'command': 'GetDoc',
        'line_num': 2,
        'column_num': 8,
        'filepath': PathToTestFile( 'common', 'src', 'test.rs' ),
      },
      'expect': {
        'response': requests.codes.ok,
        'data': has_entry( 'detailed_info',
                           'common::test\n'
                           'pub fn create_universe()\n'
                           '---\n'
                           'Be careful when using that function' ),
      }
    } )


  @SharedYcmd
  def test_Subcommands_GetType_UnknownType( self, app ):
    RunTest( app, {
      'description': 'GetType on a unknown type raises an error',
      'request': {
        'command': 'GetType',
        'line_num': 3,
        'column_num': 4,
        'filepath': PathToTestFile( 'common', 'src', 'test.rs' ),
      },
      'expect': {
        'response': requests.codes.internal_server_error,
        'data': ErrorMatcher( RuntimeError, 'Unknown type.' )
      }
    } )


  @WithRetry()
  @SharedYcmd
  def test_Subcommands_GetType_Function( self, app ):
    RunTest( app, {
      'description': 'GetType on a function returns its type',
      'request': {
        'command': 'GetType',
        'line_num': 2,
        'column_num': 22,
        'filepath': PathToTestFile( 'common', 'src', 'test.rs' ),
      },
      'expect': {
        'response': requests.codes.ok,
        'data': has_entry( 'message', 'pub fn create_universe()' ),
      }
    } )


  @SharedYcmd
  def test_Subcommands_GoToType_Basic( self, app ):
    for test in [
      # Variable
      { 'req': ( 'main.rs', 14,  5 ), 'res': ( 'test.rs', 4, 12 ) },
      # Type
      { 'req': ( 'main.rs', 13, 19 ), 'res': ( 'test.rs', 4, 12 ) },
      # Function
      { 'req': ( 'main.rs', 12, 14 ), 'res': 'Cannot jump to location' },
      # Keyword
      { 'req': ( 'main.rs',  3,  2 ), 'res': 'Cannot jump to location' },
    ]:
      with self.subTest( test = test ):
        RunGoToTest( app, 'GoToType', test )


  @WithRetry()
  @SharedYcmd
  def test_Subcommands_GoTo( self, app ):
    for test, command in itertools.product(
        [
          # Structure
          { 'req': ( 'main.rs',  8, 24 ), 'res': ( 'main.rs', 5, 8 ) },
          # Function
          { 'req': ( 'main.rs', 12, 14 ), 'res': ( 'test.rs', 2, 8 ) },
          # Implementation
          { 'req': ( 'main.rs',  9, 12 ), 'res': ( 'main.rs', 7, 7 ) },
          # Keyword
          { 'req': ( 'main.rs',  3,  2 ), 'res': 'Cannot jump to location' },
        ],
        [ 'GoToDefinition', 'GoToDeclaration', 'GoTo' ] ):
      with self.subTest( test = test, command = command ):
        RunGoToTest( app, command, test )


  @WithRetry()
  @SharedYcmd
  def test_Subcommands_GoToImplementation( self, app ):
    for test in [
      # Structure
      { 'req': ( 'main.rs',  5,  9 ), 'res': ( 'main.rs', 8, 21 ) },
      # Trait
      { 'req': ( 'main.rs',  7,  7 ), 'res': [ ( 'main.rs', 8, 21 ),
                                               ( 'main.rs', 9, 21 ) ] },
    ]:
      with self.subTest( test = test ):
        RunGoToTest( app, 'GoToImplementation', test )


  @WithRetry()
  @SharedYcmd
  def test_Subcommands_GoToImplementation_Failure( self, app ):
    RunGoToTest( app,
                 'GoToImplementation',
                 { 'req': ( 'main.rs', 11,  2 ),
                   'res': 'Cannot jump to location',
                   'exc': RuntimeError } )


  @SharedYcmd
  def test_Subcommands_GoToReferences( self, app ):
    for test in [
      # Struct
      { 'req': ( 'main.rs',  9, 22 ), 'res': [ ( 'main.rs',  6,  8 ),
                                               ( 'main.rs',  9, 21 ) ] },
      # Function
      { 'req': ( 'main.rs', 12,  8 ), 'res': [ ( 'test.rs',  2,  8 ),
                                               ( 'main.rs', 12,  5 ) ] },
      # Implementation
      { 'req': ( 'main.rs',  8, 10 ), 'res': [ ( 'main.rs',  7,  7 ),
                                               ( 'main.rs',  8,  6 ),
                                               ( 'main.rs',  9,  6 ) ] },
      # Keyword
      { 'req': ( 'main.rs',  1,  1 ), 'res': 'Cannot jump to location' }
    ]:
      with self.subTest( test = test ):
        RunGoToTest( app, 'GoToReferences', test )


  @WithRetry()
  @SharedYcmd
  def test_Subcommands_RefactorRename_Works( self, app ):
    main_filepath = PathToTestFile( 'common', 'src', 'main.rs' )
    test_filepath = PathToTestFile( 'common', 'src', 'test.rs' )

    RunTest( app, {
      'description': 'RefactorRename on a function renames all its occurences',
      'request': {
        'command': 'RefactorRename',
        'arguments': [ 'update_universe' ],
        'line_num': 12,
        'column_num': 16,
        'filepath': main_filepath
      },
      'expect': {
        'response': requests.codes.ok,
        'data': has_entries( {
          'fixits': contains_exactly( has_entries( {
            'text': '',
            'chunks': contains_exactly(
              ChunkMatcher( 'update_universe',
                            LocationMatcher( main_filepath, 12,  5 ),
                            LocationMatcher( main_filepath, 12, 20 ) ),
              ChunkMatcher( 'update_universe',
                            LocationMatcher( test_filepath,  2,  8 ),
                            LocationMatcher( test_filepath,  2, 23 ) ),
            )
          } ) )
        } )
      }
    } )


  @SharedYcmd
  def test_Subcommands_RefactorRename_Invalid( self, app ):
    RunTest( app, {
      'description': 'RefactorRename raises an error when cursor is invalid',
      'request': {
        'command': 'RefactorRename',
        'arguments': [ 'update_universe' ],
        'line_num': 15,
        'column_num': 7,
        'filepath': PathToTestFile( 'common', 'src', 'main.rs' )
      },
      'expect': {
        'response': requests.codes.internal_server_error,
        'data': ErrorMatcher( RuntimeError,
                              'Cannot rename the symbol under cursor.' )
      }
    } )


  @SharedYcmd
  def test_Subcommands_FixIt_EmptyResponse( self, app ):
    filepath = PathToTestFile( 'common', 'src', 'main.rs' )

    RunTest( app, {
      'description': 'FixIt on a line with no '
                     'codeAction returns empty response',
      'request': {
        'command': 'FixIt',
        'line_num': 16,
        'column_num': 1,
        'filepath': filepath
      },
      'expect': {
        'response': requests.codes.ok,
        'data': has_entry( 'fixits', empty() )
      }
    } )


  @SharedYcmd
  def test_Subcommands_FixIt_Basic( self, app ):
    filepath = PathToTestFile( 'common', 'src', 'main.rs' )

    RunTest( app, {
      'description': 'Simple FixIt test',
      'request': {
        'command': 'FixIt',
        'line_num': 17,
        'column_num': 2,
        'filepath': filepath
      },
      'expect': {
        'response': requests.codes.ok,
        'data': has_entries( {
          'fixits': contains_exactly( has_entries( {
            'chunks': contains_exactly(
              ChunkMatcher( 'pub(crate) ',
                            LocationMatcher( filepath, 17, 1 ),
                            LocationMatcher( filepath, 17, 1 ) )
            )
          } ) )
        } )
      },
    } )
