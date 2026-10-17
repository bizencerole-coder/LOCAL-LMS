import 'dart:async';
import 'dart:convert';
// Only IOException: dart:io's ContentType would clash with the model of that name.
import 'dart:io' show IOException;
import 'dart:typed_data';

import 'package:http/http.dart' as http;

import '../config.dart';
import 'models.dart';

enum ApiErrorKind { network, unauthorized, forbidden, notFound, rateLimited, unavailable, server, invalid, expired }

class ApiException implements Exception {
  const ApiException(this.kind, this.message, {this.statusCode, this.code});

  final ApiErrorKind kind;
  final String message;
  final int? statusCode;
  final String? code;

  /// Worth offering a "Try again" button.
  bool get isRetryable =>
      kind == ApiErrorKind.network ||
      kind == ApiErrorKind.unavailable ||
      kind == ApiErrorKind.server ||
      kind == ApiErrorKind.rateLimited ||
      kind == ApiErrorKind.expired;

  @override
  String toString() => 'ApiException($kind, $statusCode, $code): $message';
}

/// Normalises what a user types as the server address: adds http://, drops
/// trailing slashes and paths. Returns null when it is not a usable http(s)
/// address (no host, bad port, stray characters).
String? tryNormalizeServerUrl(String input) {
  var value = input.trim();
  if (value.isEmpty) return null;
  if (!value.contains('://')) value = 'http://$value';
  final uri = Uri.tryParse(value);
  if (uri == null || (uri.scheme != 'http' && uri.scheme != 'https') || uri.host.isEmpty) return null;
  if (uri.hasPort && (uri.port < 1 || uri.port > 65535)) return null;
  if (RegExp(r'[\s%@]').hasMatch(uri.host)) return null;
  return Uri(scheme: uri.scheme, host: uri.host, port: uri.hasPort ? uri.port : null).toString();
}

/// As [tryNormalizeServerUrl], but throws [FormatException] for an invalid address.
String normalizeServerUrl(String input) =>
    tryNormalizeServerUrl(input) ?? (throw FormatException('Invalid server address', input));

/// A downloaded notes or image file and the access it was downloaded with.
typedef ContentFile = ({ContentAccess access, Uint8List bytes});

/// Client for the local LMS API. Talks only to the configured campus server.
class ApiClient {
  ApiClient({
    required String baseUrl,
    this.token,
    http.Client? httpClient,
    this.onUnauthorized,
    this.onReachability,
  })  : baseUrl = normalizeServerUrl(baseUrl),
        _http = httpClient ?? http.Client();

  final String baseUrl;
  String? token;
  final http.Client _http;

  /// Called when an authenticated request gets 401 (session expired or revoked).
  final void Function()? onUnauthorized;

  /// Called with true after any response, false after a network failure.
  final void Function(bool reachable)? onReachability;

  String get _host => Uri.parse(baseUrl).host;

  Future<dynamic> _request(String method, String path, {Object? body, bool authenticated = true}) async {
    final request = http.Request(method, Uri.parse('$baseUrl$path'))
      ..headers['Accept'] = 'application/json';
    if (body != null) {
      request.headers['Content-Type'] = 'application/json';
      request.body = jsonEncode(body);
    }
    if (authenticated && token != null) {
      request.headers['Authorization'] = 'Bearer $token';
    }

    final http.Response response;
    try {
      final streamed = await _http.send(request).timeout(AppConfig.requestTimeout);
      response = await http.Response.fromStream(streamed).timeout(AppConfig.requestTimeout);
    } on TimeoutException {
      onReachability?.call(false);
      throw ApiException(ApiErrorKind.network,
          'The campus server at $_host is not responding. Check the Wi-Fi connection and try again.');
    } on http.ClientException {
      onReachability?.call(false);
      throw _unreachable();
    } on IOException {
      // SocketException, TlsException/HandshakeException (https to a plain-HTTP port), ...
      onReachability?.call(false);
      throw _unreachable();
    } on ArgumentError {
      onReachability?.call(false);
      throw _unreachable();
    }
    onReachability?.call(true);

    if (response.statusCode >= 200 && response.statusCode < 300) {
      if (response.body.isEmpty) return null;
      try {
        return jsonDecode(utf8.decode(response.bodyBytes));
      } on FormatException {
        throw _notAnLmsServer();
      }
    }
    final error = _errorFrom(response);
    if (error.kind == ApiErrorKind.unauthorized && authenticated) {
      onUnauthorized?.call();
    }
    throw error;
  }

  ApiException _unreachable([String? host]) => ApiException(ApiErrorKind.network,
      "Can't reach the campus server at ${host ?? _host}. Make sure this tablet is connected to the campus Wi-Fi.");

  /// A 2xx answer that is not the LMS API's JSON (a router page, captive portal, ...).
  ApiException _notAnLmsServer() => ApiException(ApiErrorKind.server,
      'The server at $_host did not answer like the campus LMS. Check the server address.');

  ApiException _errorFrom(http.Response response) {
    String? code;
    String? message;
    try {
      final error = (jsonDecode(utf8.decode(response.bodyBytes)) as Map<String, dynamic>)['error'];
      if (error is Map<String, dynamic>) {
        code = error['code'] as String?;
        message = error['message'] as String?;
      }
    } catch (_) {
      // Not a JSON error body (e.g. an Nginx error page).
    }
    final status = response.statusCode;
    final kind = switch (status) {
      400 || 422 => ApiErrorKind.invalid,
      401 => ApiErrorKind.unauthorized,
      403 => ApiErrorKind.forbidden,
      404 => ApiErrorKind.notFound,
      429 => ApiErrorKind.rateLimited,
      502 || 503 || 504 => ApiErrorKind.unavailable,
      _ => ApiErrorKind.server,
    };
    message ??= switch (kind) {
      ApiErrorKind.unauthorized => 'Your session has ended. Please sign in again.',
      ApiErrorKind.forbidden => 'You do not have access to this.',
      ApiErrorKind.notFound => 'This item is not available.',
      ApiErrorKind.rateLimited => 'Too many attempts. Please wait a minute and try again.',
      ApiErrorKind.unavailable => 'The campus server is starting up or busy. Please try again shortly.',
      _ => 'The campus server had a problem (HTTP $status). Please try again.',
    };
    if (kind == ApiErrorKind.rateLimited) {
      message = 'Too many attempts. Please wait a minute and try again.';
    }
    return ApiException(kind, message, statusCode: status, code: code);
  }

  /// Errors from a signed media URL. Nginx answers these itself (no JSON envelope).
  ApiException _mediaError(int status) => switch (status) {
        // 403: bad or stale signature, 410: expired. Opening the item again gives a fresh link.
        403 || 410 => ApiException(ApiErrorKind.expired, 'The link to this file has expired. Please try again.',
            statusCode: status, code: 'link_expired'),
        404 => ApiException(ApiErrorKind.notFound,
            'The file for this item is missing on the campus server. Please tell your teacher.',
            statusCode: status),
        429 => ApiException(ApiErrorKind.rateLimited, 'Too many requests. Please wait a minute and try again.',
            statusCode: status),
        502 || 503 || 504 => ApiException(ApiErrorKind.unavailable,
            'The campus server is starting up or busy. Please try again shortly.',
            statusCode: status),
        _ => ApiException(ApiErrorKind.server,
            'The campus server had a problem sending this file (HTTP $status). Please try again.',
            statusCode: status),
      };

  ApiException _tooLarge(int bytes) => ApiException(ApiErrorKind.invalid,
      'This file is too large to open on this tablet (${(bytes / (1024 * 1024)).ceil()} MB).',
      code: 'file_too_large');

  List<Map<String, dynamic>> _list(dynamic json) {
    if (json is List && json.every((e) => e is Map<String, dynamic>)) return json.cast<Map<String, dynamic>>();
    throw _notAnLmsServer();
  }

  Map<String, dynamic> _map(dynamic json) {
    if (json is Map<String, dynamic>) return json;
    throw _notAnLmsServer();
  }

  // --------------------------------------------------------------- endpoints

  /// True if the server answers `/health`. Never throws.
  Future<bool> ping() async {
    try {
      _map(await _request('GET', '/health', authenticated: false));
      return true;
    } catch (_) {
      return false;
    }
  }

  Future<LoginResult> login(String username, String password) async {
    final json = _map(await _request('POST', '/api/v1/auth/login',
        body: {'username': username, 'password': password}, authenticated: false));
    return LoginResult(
      token: json['access_token'] as String,
      student: Student.fromLogin(json['student'] as Map<String, dynamic>),
      expiresIn: Duration(seconds: json['expires_in'] as int? ?? 0),
    );
  }

  Future<void> logout() => _request('POST', '/api/v1/auth/logout');

  /// The school's name, colour and logo. No sign-in needed: the sign-in screen shows them.
  Future<SchoolProfile> school() async =>
      SchoolProfile.fromJson(_map(await _request('GET', '/api/v1/school', authenticated: false)));

  /// Notices for this student: important ones first, then newest.
  Future<List<NoticeItem>> notices({int limit = 50}) async =>
      _list(await _request('GET', '/api/v1/notices?limit=$limit')).map(NoticeItem.fromJson).toList();

  /// The home page's banner slides, in the order staff set.
  Future<List<BannerItem>> banners() async =>
      _list(await _request('GET', '/api/v1/banners')).map(BannerItem.fromJson).toList();

  /// An absolute URL for a path the server returned (logo and banner pictures).
  Uri resolve(String path) => Uri.parse(baseUrl).resolve(path);

  Future<Student> me() async =>
      Student.fromMe(_map(await _request('GET', '/api/v1/me')));

  Future<List<SubjectItem>> subjects() async =>
      _list(await _request('GET', '/api/v1/subjects')).map(SubjectItem.fromJson).toList();

  Future<List<ModuleItem>> modules(String subjectId) async =>
      _list(await _request('GET', '/api/v1/subjects/$subjectId/modules')).map(ModuleItem.fromJson).toList();

  Future<List<ContentItem>> contents(String moduleId) async =>
      _list(await _request('GET', '/api/v1/modules/$moduleId/contents')).map(ContentItem.fromJson).toList();

  /// One item, with `moduleTitle`, `subjectId` and `subjectName` filled in.
  Future<ContentItem> content(String contentId) async =>
      ContentItem.fromJson(_map(await _request('GET', '/api/v1/contents/$contentId')));

  /// Recently watched or opened items, newest first. With [includeCompleted] false
  /// these are the videos still in progress ("Continue watching").
  Future<List<ContinueItem>> continueItems({int limit = 10, bool includeCompleted = false}) async => _list(
          await _request('GET', '/api/v1/me/continue?limit=$limit&include_completed=$includeCompleted'))
      .map(ContinueItem.fromJson)
      .toList();

  /// A short-lived signed URL for the item's file. For notes and images the server
  /// records the item as opened; videos report progress with [saveProgress].
  Future<ContentAccess> openContent(String contentId) async => ContentAccess.fromJson(
      _map(await _request('POST', '/api/v1/contents/$contentId/open')),
      base: Uri.parse(baseUrl));

  Future<Progress> progress(String contentId) async =>
      Progress.fromJson(_map(await _request('GET', '/api/v1/contents/$contentId/progress')));

  Future<Progress> saveProgress(
    String contentId, {
    required int positionSeconds,
    int? durationSeconds,
    bool completed = false,
  }) async =>
      Progress.fromJson(_map(await _request('PUT', '/api/v1/contents/$contentId/progress', body: {
        'position_seconds': positionSeconds,
        'duration_seconds': ?durationSeconds,
        'is_completed': completed,
      })));

  /// Opens a notes or image item and downloads its file. A link that has already
  /// expired when the download starts (403/410) is replaced by opening the item once more.
  Future<ContentFile> fetchContentFile(
    String contentId, {
    int maxBytes = AppConfig.maxFileBytes,
    void Function(int received, int? total)? onProgress,
  }) async {
    for (var attempt = 1;; attempt++) {
      final access = await openContent(contentId);
      final size = access.fileSizeBytes;
      if (size != null && size > maxBytes) throw _tooLarge(size);
      try {
        final bytes = await downloadFile(access.url,
            maxBytes: maxBytes, timeout: _downloadTimeout(size), onProgress: onProgress);
        return (access: access, bytes: bytes);
      } on ApiException catch (e) {
        if (e.kind != ApiErrorKind.expired || attempt >= 2) rethrow;
      }
    }
  }

  /// [AppConfig.downloadTimeout], or longer for a big file so that a slow but working
  /// connection (about 2 Mbit/s) can still finish it.
  static Duration _downloadTimeout(int? bytes) {
    const bytesPerSecond = 256 * 1024;
    final needed = Duration(seconds: 10 + (bytes ?? 0) ~/ bytesPerSecond);
    return needed > AppConfig.downloadTimeout ? needed : AppConfig.downloadTimeout;
  }

  /// Downloads a signed media URL (from [openContent]) into memory. The signature in
  /// the URL is the permission, so no Authorization header is sent. Gives up when the
  /// server sends nothing for [AppConfig.requestTimeout], when the whole download takes
  /// longer than [timeout], or when the file is larger than [maxBytes].
  ///
  /// Throws [ApiException]; a link that ran out (403/410) is [ApiErrorKind.expired].
  Future<Uint8List> downloadFile(
    Uri url, {
    int maxBytes = AppConfig.maxFileBytes,
    Duration timeout = AppConfig.downloadTimeout,
    void Function(int received, int? total)? onProgress,
  }) async {
    final stopwatch = Stopwatch()..start();
    final http.StreamedResponse response;
    try {
      response = await _http.send(http.Request('GET', url)).timeout(AppConfig.requestTimeout);
    } on TimeoutException {
      onReachability?.call(false);
      throw ApiException(ApiErrorKind.network,
          'The campus server at ${url.host} is not responding. Check the Wi-Fi connection and try again.');
    } on http.ClientException {
      onReachability?.call(false);
      throw _unreachable(url.host);
    } on IOException {
      onReachability?.call(false);
      throw _unreachable(url.host);
    } on ArgumentError {
      onReachability?.call(false);
      throw _unreachable(url.host);
    }
    onReachability?.call(true);

    final status = response.statusCode;
    if (status < 200 || status >= 300) {
      unawaited(response.stream.drain<void>().catchError((_) {}));
      throw _mediaError(status);
    }
    final total = response.contentLength;
    if (total != null && total > maxBytes) {
      unawaited(response.stream.listen(null).cancel());
      throw _tooLarge(total);
    }

    final remaining = timeout - stopwatch.elapsed;
    try {
      return await _readBody(response, total: total, maxBytes: maxBytes, timeout: remaining, onProgress: onProgress);
    } on ApiException {
      rethrow;
    } on TimeoutException {
      onReachability?.call(false);
      throw const ApiException(ApiErrorKind.network,
          'The download is taking too long. Check the Wi-Fi connection and try again.');
    } catch (_) {
      // ClientException or IOException: the connection dropped part-way.
      onReachability?.call(false);
      throw const ApiException(ApiErrorKind.network,
          'The download was interrupted. Check the Wi-Fi connection and try again.');
    }
  }

  /// Collects the body, into a buffer of the announced size when there is one.
  Future<Uint8List> _readBody(
    http.StreamedResponse response, {
    required int? total,
    required int maxBytes,
    required Duration timeout,
    void Function(int received, int? total)? onProgress,
  }) {
    final completer = Completer<Uint8List>();
    final fixed = total == null ? null : Uint8List(total);
    final builder = BytesBuilder(copy: false);
    var received = 0;
    late final StreamSubscription<List<int>> subscription;
    late final Timer deadline;

    void fail(Object error) {
      deadline.cancel();
      unawaited(subscription.cancel());
      if (!completer.isCompleted) completer.completeError(error);
    }

    deadline = Timer(timeout.isNegative ? Duration.zero : timeout, () => fail(TimeoutException('download')));
    subscription = response.stream.timeout(AppConfig.requestTimeout).listen(
      (chunk) {
        final start = received;
        received += chunk.length;
        if (received > maxBytes) {
          fail(_tooLarge(received));
        } else if (fixed != null && received > fixed.length) {
          fail(const FormatException('More data than announced'));
        } else {
          if (fixed != null) {
            fixed.setRange(start, received, chunk);
          } else {
            builder.add(chunk);
          }
          onProgress?.call(received, total);
        }
      },
      onError: fail,
      onDone: () {
        deadline.cancel();
        if (completer.isCompleted) return;
        if (fixed != null && received != fixed.length) {
          completer.completeError(const FormatException('Download ended early'));
        } else {
          completer.complete(fixed ?? builder.takeBytes());
        }
      },
      // fail() cancels; with cancelOnError the error would wait for that cancel to finish.
    );
    return completer.future;
  }

  void close() => _http.close();
}
