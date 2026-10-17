import 'dart:async';
import 'dart:convert';
import 'dart:io' show SocketException;

import 'package:campus_lms/api/api_client.dart';
import 'package:campus_lms/api/models.dart';
import 'package:fake_async/fake_async.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

http.Response jsonResponse(Object body, [int status = 200]) =>
    http.Response(jsonEncode(body), status, headers: {'content-type': 'application/json'});

/// A signed-in client whose server answers every request with [handler].
ApiClient clientWith(Future<http.Response> Function(http.Request request) handler) =>
    ApiClient(baseUrl: 'http://lms', token: 't', httpClient: MockClient(handler));

Map<String, dynamic> openJson({String url = 'http://lms/media/n.pdf', int? size}) => {
      'content_id': 'n1',
      'type': 'pdf',
      'title': 'Python Basics: Notes',
      'url': url,
      'expires_at': '2026-10-16T15:00:00Z',
      'mime_type': 'application/pdf',
      'duration_seconds': null,
      'file_size_bytes': size,
      'resume_position_seconds': 0,
      'is_completed': true,
    };

TypeMatcher<ApiException> apiError(ApiErrorKind kind) => isA<ApiException>().having((e) => e.kind, 'kind', kind);

final _mediaUrl = Uri.parse('http://lms/media/class12/cs/notes.pdf?expires=1&md5=m');

void main() {
  group('normalizeServerUrl', () {
    test('adds a scheme and drops trailing slashes and paths', () {
      expect(normalizeServerUrl('192.168.10.10'), 'http://192.168.10.10');
      expect(normalizeServerUrl(' http://lms.campus.lan/ '), 'http://lms.campus.lan');
      expect(normalizeServerUrl('http://localhost:8080/api/v1'), 'http://localhost:8080');
      expect(normalizeServerUrl('https://lms.campus.lan'), 'https://lms.campus.lan');
    });

    test('rejects addresses a tablet could not use', () {
      expect(tryNormalizeServerUrl(''), isNull);
      expect(tryNormalizeServerUrl('http://'), isNull);
      expect(tryNormalizeServerUrl('192.168.10.10:808O'), isNull);
      expect(tryNormalizeServerUrl('192.168.10.10:70000'), isNull);
      expect(tryNormalizeServerUrl('ftp://lms.campus.lan'), isNull);
      expect(tryNormalizeServerUrl('[fe80::1]:8080'), 'http://[fe80::1]:8080');
      expect(() => normalizeServerUrl('http://'), throwsFormatException);
    });
  });

  test('a non-JSON 2xx answer is reported as "not the LMS server", and ping never throws', () async {
    final client = ApiClient(
      baseUrl: 'http://192.168.10.1',
      httpClient: MockClient((_) async => http.Response('<html>Router login</html>', 200)),
    );
    await expectLater(client.subjects(), throwsA(apiError(ApiErrorKind.server)));
    expect(await client.ping(), isFalse);
  });

  test('login posts credentials and parses the session, including the batch', () async {
    late http.Request sent;
    final client = ApiClient(
      baseUrl: 'http://192.168.10.10',
      httpClient: MockClient((request) async {
        sent = request;
        return jsonResponse({
          'access_token': 'tok',
          'token_type': 'bearer',
          'expires_in': 3600,
          'student': {'id': 'u1', 'full_name': 'Demo Student', 'class_name': 'Class 12', 'batch_name': '2026-27'},
        });
      }),
    );
    final result = await client.login('demo.student', 'pw');
    expect(sent.url.toString(), 'http://192.168.10.10/api/v1/auth/login');
    expect(jsonDecode(sent.body), {'username': 'demo.student', 'password': 'pw'});
    expect(sent.headers.containsKey('Authorization'), isFalse);
    expect(result.token, 'tok');
    expect(result.student.className, 'Class 12');
    expect(result.student.batchName, '2026-27');
    expect(result.expiresIn, const Duration(hours: 1));
  });

  test('me reads the class and batch objects', () async {
    final client = clientWith((request) async {
      expect(request.url.path, '/api/v1/me');
      return jsonResponse({
        'id': 'u1',
        'student_code': 'DEMO-12-001',
        'username': 'demo.student',
        'full_name': 'Demo Student',
        'class': {'id': 'k1', 'name': 'Class 12'},
        'batch': {'id': 'b1', 'name': '2026-27'},
      });
    });
    final me = await client.me();
    expect(me.groupLabel, '2026-27 · Class 12');
    expect(me.studentCode, 'DEMO-12-001');
  });

  test('subjects send the bearer token and carry module and per-type counts', () async {
    final client = ApiClient(
      baseUrl: 'http://lms',
      token: 'tok',
      httpClient: MockClient((request) async {
        expect(request.method, 'GET');
        expect(request.url.path, '/api/v1/subjects');
        expect(request.headers['Authorization'], 'Bearer tok');
        return jsonResponse([
          {
            'id': 's1',
            'name': 'Computer Science',
            'description': 'Programming with Python',
            'sort_order': 1,
            'module_count': 4,
            'content_count': 9,
            'video_count': 6,
            'notes_count': 2,
            'image_count': 1,
            'chapter_count': 1,
          },
        ]);
      }),
    );
    final subject = (await client.subjects()).single;
    expect(subject.name, 'Computer Science');
    expect(subject.description, 'Programming with Python');
    expect([subject.moduleCount, subject.contentCount, subject.videoCount, subject.notesCount, subject.imageCount],
        [4, 9, 6, 2, 1]);
  });

  test('modules of a subject', () async {
    final client = clientWith((request) async {
      expect(request.url.path, '/api/v1/subjects/s1/modules');
      return jsonResponse([
        {
          'id': 'm1',
          'subject_id': 's1',
          'title': 'Python Basics',
          'description': null,
          'sort_order': 1,
          'content_count': 3,
          'video_count': 2,
          'notes_count': 1,
          'image_count': 0,
        },
      ]);
    });
    final module = (await client.modules('s1')).single;
    expect(module.title, 'Python Basics');
    expect(module.subjectId, 's1');
    expect(module.description, isNull);
    expect([module.contentCount, module.videoCount, module.notesCount, module.imageCount], [3, 2, 1, 0]);
  });

  test('contents of a module: every type, an unknown type, and missing optional fields', () async {
    final client = clientWith((request) async {
      expect(request.url.path, '/api/v1/modules/m1/contents');
      return jsonResponse([
        {
          'id': 'v2',
          'module_id': 'm1',
          'type': 'video',
          'title': 'Lesson 2: Python Functions',
          'description': null,
          'sort_order': 2,
          'duration_seconds': 1200,
          'file_size_bytes': 52428800,
          'progress': {
            'content_id': 'v2',
            'position_seconds': 300,
            'duration_seconds': 1200,
            'is_completed': false,
            'last_watched_at': '2026-10-15T14:30:00Z',
          },
        },
        {
          'id': 'n1',
          'module_id': 'm1',
          'type': 'pdf',
          'title': 'Python Basics: Notes',
          'description': 'Summary of the module',
          'sort_order': 3,
          'duration_seconds': null,
          'file_size_bytes': 2411725,
          'progress': {
            'content_id': 'n1',
            'position_seconds': 0,
            'duration_seconds': null,
            'is_completed': true,
            'last_watched_at': null,
          },
        },
        {'id': 'i1', 'type': 'image', 'title': 'Flowchart'},
        {
          'id': 'q1',
          'module_id': 'm1',
          'type': 'quiz',
          'title': 'Quick quiz',
          'description': null,
          'sort_order': 5,
          'duration_seconds': null,
          'file_size_bytes': null,
          'progress': null,
        },
      ]);
    });
    final items = await client.contents('m1');
    expect(items.map((c) => c.type), [ContentType.video, ContentType.pdf, ContentType.image, ContentType.unknown]);

    final video = items[0];
    expect(video.progress!.contentId, 'v2');
    expect(video.progress!.positionSeconds, 300);
    expect(video.progress!.fraction(video.durationSeconds), closeTo(0.25, 1e-9));
    expect(video.progress!.lastWatchedAt, DateTime.utc(2026, 10, 15, 14, 30));

    final notes = items[1];
    expect(notes.fileSizeBytes, 2411725);
    expect(notes.isCompleted, isTrue);
    expect(notes.progress!.lastWatchedAt, isNull);

    final image = items[2];
    expect(image.moduleId, isNull);
    expect(image.description, isNull);
    expect(image.durationSeconds, isNull);
    expect(image.fileSizeBytes, isNull);
    expect(image.progress, isNull);
    expect(image.isCompleted, isFalse);

    expect(items[3].title, 'Quick quiz');
  });

  test('one content item comes with its module and subject', () async {
    final client = clientWith((request) async {
      expect(request.url.path, '/api/v1/contents/v2');
      return jsonResponse({
        'id': 'v2',
        'module_id': 'm1',
        'type': 'video',
        'title': 'Lesson 2: Python Functions',
        'description': null,
        'sort_order': 2,
        'duration_seconds': 480,
        'file_size_bytes': null,
        'progress': null,
        'module_title': 'Python Basics',
        'subject_id': 's1',
        'subject_name': 'Computer Science',
      });
    });
    final item = await client.content('v2');
    expect(item.moduleTitle, 'Python Basics');
    expect(item.subjectId, 's1');
    expect(item.subjectName, 'Computer Science');
  });

  test('openContent posts to /open and parses the signed URL', () async {
    final client = clientWith((request) async {
      expect(request.method, 'POST');
      expect(request.url.path, '/api/v1/contents/v2/open');
      expect(request.headers['Authorization'], 'Bearer t');
      return jsonResponse({
        'content_id': 'v2',
        'type': 'video',
        'title': 'Lesson 2: Python Functions',
        'url': 'http://lms/media/class12/cs/02.mp4?expires=1&md5=m',
        'expires_at': '2026-10-15T15:00:00Z',
        'mime_type': 'video/mp4',
        'duration_seconds': 1200,
        'file_size_bytes': null,
        'resume_position_seconds': 765,
        'is_completed': false,
      });
    });
    final access = await client.openContent('v2');
    expect(access.type, ContentType.video);
    expect(access.url.path, '/media/class12/cs/02.mp4');
    expect(access.expiresAt, DateTime.utc(2026, 10, 15, 15));
    expect(access.mimeType, 'video/mp4');
    expect(access.durationSeconds, 1200);
    expect(access.fileSizeBytes, isNull);
    expect(access.resumePositionSeconds, 765);
    expect(access.isCompleted, isFalse);
  });

  test('a signed URL given relative to the server is made absolute', () async {
    final client = clientWith((_) async => jsonResponse(openJson(url: '/media/n.pdf?md5=m')));
    final access = await client.openContent('n1');
    expect(access.url.toString(), 'http://lms/media/n.pdf?md5=m');
  });

  test('progress is read and saved per content item', () async {
    final requests = <http.Request>[];
    final client = clientWith((request) async {
      requests.add(request);
      return jsonResponse({
        'content_id': 'v2',
        'position_seconds': 765,
        'duration_seconds': 1200,
        'is_completed': false,
        'last_watched_at': '2026-10-15T14:30:00Z',
      });
    });
    final read = await client.progress('v2');
    final saved = await client.saveProgress('v2', positionSeconds: 765, durationSeconds: 1200);
    expect(requests.map((r) => '${r.method} ${r.url.path}'),
        ['GET /api/v1/contents/v2/progress', 'PUT /api/v1/contents/v2/progress']);
    expect(jsonDecode(requests[1].body), {'position_seconds': 765, 'duration_seconds': 1200, 'is_completed': false});
    expect(read.contentId, 'v2');
    expect(saved.positionSeconds, 765);
  });

  test('saveProgress leaves out an unknown duration', () async {
    late Map<String, dynamic> body;
    final client = clientWith((request) async {
      body = jsonDecode(request.body) as Map<String, dynamic>;
      return jsonResponse({'content_id': 'v2', 'position_seconds': 1200, 'is_completed': true});
    });
    final saved = await client.saveProgress('v2', positionSeconds: 1200, completed: true);
    expect(body, {'position_seconds': 1200, 'is_completed': true});
    expect(saved.isCompleted, isTrue);
  });

  test('continueItems asks /me/continue with the limit and completion filter', () async {
    final queries = <String>[];
    final client = clientWith((request) async {
      expect(request.url.path, '/api/v1/me/continue');
      queries.add(request.url.query);
      return jsonResponse([
        {
          'content': {
            'id': 'v2',
            'module_id': 'm1',
            'type': 'video',
            'title': 'Lesson 2: Python Functions',
            'duration_seconds': 480,
            'progress': {'content_id': 'v2', 'position_seconds': 120, 'is_completed': false},
          },
          'module_title': 'Python Basics',
          'subject_name': 'Computer Science',
        },
      ]);
    });
    final watching = await client.continueItems(limit: 5);
    await client.continueItems(limit: 50, includeCompleted: true);
    expect(queries, ['limit=5&include_completed=false', 'limit=50&include_completed=true']);
    final item = watching.single;
    expect(item.content.title, 'Lesson 2: Python Functions');
    expect(item.content.progress!.positionSeconds, 120);
    expect(item.location, 'Computer Science › Python Basics');
  });

  test('server error messages are passed through', () async {
    final client = ApiClient(
      baseUrl: 'http://lms',
      httpClient: MockClient((_) async => jsonResponse({
            'error': {'code': 'invalid_credentials', 'message': 'Incorrect username or password.'},
          }, 401)),
    );
    await expectLater(
      client.login('x', 'y'),
      throwsA(apiError(ApiErrorKind.unauthorized)
          .having((e) => e.message, 'message', 'Incorrect username or password.')),
    );
  });

  test('401 on an authenticated call triggers sign-out', () async {
    var signedOut = false;
    final client = ApiClient(
      baseUrl: 'http://lms',
      token: 'expired',
      onUnauthorized: () => signedOut = true,
      httpClient: MockClient((_) async => jsonResponse({'error': {'code': 'unauthorized', 'message': 'x'}}, 401)),
    );
    await expectLater(client.subjects(), throwsA(isA<ApiException>()));
    expect(signedOut, isTrue);
  });

  test('network failures are reported as unreachable', () async {
    bool? reachable;
    final client = ApiClient(
      baseUrl: 'http://192.168.10.10',
      onReachability: (ok) => reachable = ok,
      httpClient: MockClient((_) async => throw const SocketException('No route to host')),
    );
    await expectLater(
      client.subjects(),
      throwsA(apiError(ApiErrorKind.network)
          .having((e) => e.isRetryable, 'retryable', isTrue)
          .having((e) => e.message, 'message', contains('192.168.10.10'))),
    );
    expect(reachable, isFalse);
  });

  test('non-JSON error pages still give a friendly message', () async {
    final client = ApiClient(
      baseUrl: 'http://lms',
      httpClient: MockClient((_) async => http.Response('<html>502 Bad Gateway</html>', 502)),
    );
    await expectLater(client.subjects(), throwsA(apiError(ApiErrorKind.unavailable)));
  });

  test('openContent errors: not available (404) and file missing (503)', () async {
    final client = clientWith((request) async => request.url.path.endsWith('/gone/open')
        ? jsonResponse({'error': {'code': 'not_found', 'message': 'This item is not available.'}}, 404)
        : jsonResponse({'error': {'code': 'media_unavailable', 'message': 'The file is missing.'}}, 503));
    await expectLater(client.openContent('gone'),
        throwsA(apiError(ApiErrorKind.notFound).having((e) => e.isRetryable, 'retryable', isFalse)));
    await expectLater(client.openContent('missing'),
        throwsA(apiError(ApiErrorKind.unavailable).having((e) => e.code, 'code', 'media_unavailable')));
  });

  group('downloadFile', () {
    test('returns the bytes, sends no session token and reports progress', () async {
      late http.BaseRequest sent;
      bool? reachable;
      final client = ApiClient(
        baseUrl: 'http://lms',
        token: 'secret',
        onReachability: (ok) => reachable = ok,
        httpClient: MockClient.streaming((request, _) async {
          sent = request;
          return http.StreamedResponse(Stream.fromIterable([
            [37, 80, 68],
            [70, 45],
          ]), 200, contentLength: 5);
        }),
      );
      final progress = <(int, int?)>[];
      final bytes =
          await client.downloadFile(_mediaUrl, onProgress: (received, total) => progress.add((received, total)));
      expect(bytes, [37, 80, 68, 70, 45]);
      expect(sent.method, 'GET');
      expect(sent.url, _mediaUrl);
      expect(sent.headers.containsKey('Authorization'), isFalse);
      expect(progress, [(3, 5), (5, 5)]);
      expect(reachable, isTrue);
    });

    test('works without a Content-Length', () async {
      final client = ApiClient(
        baseUrl: 'http://lms',
        httpClient: MockClient.streaming((_, _) async => http.StreamedResponse(Stream.fromIterable([
              [1, 2],
              [3],
            ]), 200)),
      );
      expect(await client.downloadFile(_mediaUrl), [1, 2, 3]);
    });

    test('403 and 410 from the media URL mean the link expired: retryable', () async {
      for (final status in [403, 410]) {
        final client = ApiClient(
          baseUrl: 'http://lms',
          httpClient: MockClient((_) async => http.Response('<html>$status</html>', status)),
        );
        await expectLater(
          client.downloadFile(_mediaUrl),
          throwsA(apiError(ApiErrorKind.expired)
              .having((e) => e.statusCode, 'status', status)
              .having((e) => e.isRetryable, 'retryable', isTrue)),
        );
      }
    });

    test('other media errors keep their meaning', () async {
      Future<void> expectStatus(int status, ApiErrorKind kind) async {
        final client = ApiClient(
          baseUrl: 'http://lms',
          httpClient: MockClient((_) async => http.Response('<html>error</html>', status)),
        );
        await expectLater(client.downloadFile(_mediaUrl), throwsA(apiError(kind)));
      }

      await expectStatus(404, ApiErrorKind.notFound);
      await expectStatus(503, ApiErrorKind.unavailable);
      await expectStatus(500, ApiErrorKind.server);
    });

    test('an unreachable server is a network error', () async {
      bool? reachable;
      final client = ApiClient(
        baseUrl: 'http://192.168.10.10',
        onReachability: (ok) => reachable = ok,
        httpClient: MockClient((_) async => throw const SocketException('Network is unreachable')),
      );
      await expectLater(
        client.downloadFile(Uri.parse('http://192.168.10.10/media/n.pdf')),
        throwsA(apiError(ApiErrorKind.network).having((e) => e.message, 'message', contains('192.168.10.10'))),
      );
      expect(reachable, isFalse);
    });

    test('a file larger than allowed is refused, by Content-Length or while arriving', () async {
      final announced = ApiClient(
        baseUrl: 'http://lms',
        httpClient: MockClient.streaming(
            (_, _) async => http.StreamedResponse(Stream.value(List.filled(10, 0)), 200, contentLength: 5000)),
      );
      await expectLater(
        announced.downloadFile(_mediaUrl, maxBytes: 1000),
        throwsA(apiError(ApiErrorKind.invalid).having((e) => e.code, 'code', 'file_too_large')),
      );

      final unannounced = ApiClient(
        baseUrl: 'http://lms',
        httpClient: MockClient.streaming((_, _) async => http.StreamedResponse(
            Stream.fromIterable([List.filled(600, 0), List.filled(600, 0)]), 200)),
      );
      await expectLater(
        unannounced.downloadFile(_mediaUrl, maxBytes: 1000),
        throwsA(apiError(ApiErrorKind.invalid).having((e) => e.code, 'code', 'file_too_large')),
      );
    });

    test('a connection that drops part-way is a retryable network error', () async {
      final dropped = ApiClient(
        baseUrl: 'http://lms',
        httpClient: MockClient.streaming((_, _) async {
          final body = StreamController<List<int>>();
          body.add([1, 2, 3]);
          body.addError(http.ClientException('Connection closed while receiving data'));
          unawaited(body.close());
          return http.StreamedResponse(body.stream, 200, contentLength: 100);
        }),
      );
      await expectLater(
        dropped.downloadFile(_mediaUrl),
        throwsA(apiError(ApiErrorKind.network).having((e) => e.isRetryable, 'retryable', isTrue)),
      );

      final short = ApiClient(
        baseUrl: 'http://lms',
        httpClient: MockClient.streaming(
            (_, _) async => http.StreamedResponse(Stream.value([1, 2, 3]), 200, contentLength: 100)),
      );
      await expectLater(short.downloadFile(_mediaUrl), throwsA(apiError(ApiErrorKind.network)));
    });

    test('a server that stops sending gives up after the request timeout', () {
      fakeAsync((async) {
        final body = StreamController<List<int>>();
        bool? reachable;
        final client = ApiClient(
          baseUrl: 'http://lms',
          onReachability: (ok) => reachable = ok,
          httpClient:
              MockClient.streaming((_, _) async => http.StreamedResponse(body.stream, 200, contentLength: 1000)),
        );
        Object? error;
        client.downloadFile(_mediaUrl).then((_) {}, onError: (Object e) {
          error = e;
        });
        async.flushMicrotasks();
        body.add(List.filled(100, 1));
        async.elapse(const Duration(seconds: 9));
        expect(error, isNull);
        async.elapse(const Duration(seconds: 2));
        expect(error, apiError(ApiErrorKind.network));
        expect(reachable, isFalse);
      });
    });

    test('a download slower than its time limit gives up', () {
      fakeAsync((async) {
        final body = StreamController<List<int>>();
        final client = ApiClient(
          baseUrl: 'http://lms',
          httpClient: MockClient.streaming((_, _) async => http.StreamedResponse(body.stream, 200)),
        );
        Object? error;
        client
            .downloadFile(_mediaUrl, timeout: const Duration(seconds: 60))
            .then((_) {}, onError: (Object e) {
          error = e;
        });
        async.flushMicrotasks();
        var elapsed = 0;
        while (error == null && elapsed < 120) {
          body.add([1, 2, 3]); // a trickle: never idle long enough for the request timeout
          async.elapse(const Duration(seconds: 5));
          elapsed += 5;
        }
        expect(elapsed, inInclusiveRange(60, 65));
        expect(error, apiError(ApiErrorKind.network));
      });
    });
  });

  group('fetchContentFile', () {
    test('opens the item again when its link has expired, then downloads', () async {
      var opens = 0;
      final downloads = <Uri>[];
      final client = clientWith((request) async {
        if (request.url.path == '/api/v1/contents/n1/open') {
          opens++;
          return jsonResponse(openJson(url: 'http://lms/media/n.pdf?sig=$opens', size: 4));
        }
        downloads.add(request.url);
        expect(request.headers.containsKey('Authorization'), isFalse);
        return opens == 1 ? http.Response('<html>410 Gone</html>', 410) : http.Response.bytes([37, 80, 68, 70], 200);
      });
      final file = await client.fetchContentFile('n1');
      expect(opens, 2);
      expect(downloads.map((u) => u.queryParameters['sig']), ['1', '2']);
      expect(file.bytes, [37, 80, 68, 70]);
      expect(file.access.type, ContentType.pdf);
    });

    test('a link refused again is reported as expired, so the viewer can offer Try again', () async {
      var opens = 0;
      final client = clientWith((request) async {
        if (request.url.path.endsWith('/open')) {
          opens++;
          return jsonResponse(openJson());
        }
        return http.Response('<html>403 Forbidden</html>', 403);
      });
      await expectLater(client.fetchContentFile('n1'), throwsA(apiError(ApiErrorKind.expired)));
      expect(opens, 2);
    });

    test('other download errors are not retried', () async {
      var opens = 0;
      final client = clientWith((request) async {
        if (request.url.path.endsWith('/open')) {
          opens++;
          return jsonResponse(openJson());
        }
        return http.Response('<html>404 Not Found</html>', 404);
      });
      await expectLater(client.fetchContentFile('n1'), throwsA(apiError(ApiErrorKind.notFound)));
      expect(opens, 1);
    });

    test('a file the server says is too large is not downloaded', () async {
      var downloads = 0;
      final client = clientWith((request) async {
        if (request.url.path.endsWith('/open')) return jsonResponse(openJson(size: 300 * 1024 * 1024));
        downloads++;
        return http.Response.bytes([1], 200);
      });
      await expectLater(
        client.fetchContentFile('n1'),
        throwsA(apiError(ApiErrorKind.invalid).having((e) => e.message, 'message', contains('300 MB'))),
      );
      expect(downloads, 0);
    });
  });
}
