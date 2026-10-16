import 'dart:convert';
import 'dart:io';

import 'package:campus_lms/api/api_client.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

http.Response jsonResponse(Object body, [int status = 200]) =>
    http.Response(jsonEncode(body), status, headers: {'content-type': 'application/json'});

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
    await expectLater(
      client.subjects(),
      throwsA(isA<ApiException>().having((e) => e.kind, 'kind', ApiErrorKind.server)),
    );
    expect(await client.ping(), isFalse);
  });

  test('login posts credentials and parses the session', () async {
    late http.Request sent;
    final client = ApiClient(
      baseUrl: 'http://192.168.10.10',
      httpClient: MockClient((request) async {
        sent = request;
        return jsonResponse({
          'access_token': 'tok',
          'token_type': 'bearer',
          'expires_in': 3600,
          'student': {'id': 'u1', 'full_name': 'Demo Student', 'class_name': 'Class 12'},
        });
      }),
    );
    final result = await client.login('demo.student', 'pw');
    expect(sent.url.toString(), 'http://192.168.10.10/api/v1/auth/login');
    expect(jsonDecode(sent.body), {'username': 'demo.student', 'password': 'pw'});
    expect(sent.headers.containsKey('Authorization'), isFalse);
    expect(result.token, 'tok');
    expect(result.student.className, 'Class 12');
    expect(result.expiresIn, const Duration(hours: 1));
  });

  test('sends the bearer token and parses lists', () async {
    final client = ApiClient(
      baseUrl: 'http://lms',
      token: 'tok',
      httpClient: MockClient((request) async {
        expect(request.headers['Authorization'], 'Bearer tok');
        return jsonResponse([
          {
            'id': 'v1',
            'chapter_id': 'c1',
            'title': 'Lesson 1',
            'description': null,
            'duration_seconds': 1200,
            'sort_order': 1,
            'progress': {
              'video_id': 'v1',
              'position_seconds': 300,
              'duration_seconds': 1200,
              'is_completed': false,
              'last_watched_at': '2026-10-15T14:30:00Z',
            },
          },
        ]);
      }),
    );
    final videos = await client.videos('c1');
    expect(videos.single.title, 'Lesson 1');
    expect(videos.single.progress!.positionSeconds, 300);
    expect(videos.single.progress!.fraction(1200), closeTo(0.25, 1e-9));
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
      throwsA(isA<ApiException>()
          .having((e) => e.kind, 'kind', ApiErrorKind.unauthorized)
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
      throwsA(isA<ApiException>()
          .having((e) => e.kind, 'kind', ApiErrorKind.network)
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
    await expectLater(
      client.subjects(),
      throwsA(isA<ApiException>().having((e) => e.kind, 'kind', ApiErrorKind.unavailable)),
    );
  });

  test('saveProgress sends position, duration and completion', () async {
    late Map<String, dynamic> body;
    final client = ApiClient(
      baseUrl: 'http://lms',
      token: 't',
      httpClient: MockClient((request) async {
        expect(request.method, 'PUT');
        expect(request.url.path, '/api/v1/videos/v1/progress');
        body = jsonDecode(request.body) as Map<String, dynamic>;
        return jsonResponse({
          'video_id': 'v1',
          'position_seconds': 765,
          'duration_seconds': 1200,
          'is_completed': false,
          'last_watched_at': '2026-10-15T14:30:00Z',
        });
      }),
    );
    final saved = await client.saveProgress('v1', positionSeconds: 765, durationSeconds: 1200);
    expect(body, {'position_seconds': 765, 'duration_seconds': 1200, 'is_completed': false});
    expect(saved.positionSeconds, 765);
  });

  test('playback info parses the signed URL', () async {
    final client = ApiClient(
      baseUrl: 'http://lms',
      token: 't',
      httpClient: MockClient((_) async => jsonResponse({
            'video_id': 'v1',
            'title': 'Python Functions',
            'playback_url': 'http://lms/media/class12/cs/a.mp4?expires=1&sid=s&md5=m',
            'expires_at': '2026-10-15T15:00:00Z',
            'duration_seconds': 1200,
            'mime_type': 'video/mp4',
            'resume_position_seconds': 765,
            'is_completed': false,
          })),
    );
    final info = await client.authorizePlayback('v1');
    expect(info.url.path, '/media/class12/cs/a.mp4');
    expect(info.resumePositionSeconds, 765);
  });
}
