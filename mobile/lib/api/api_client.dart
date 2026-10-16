import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:http/http.dart' as http;

import '../config.dart';
import 'models.dart';

enum ApiErrorKind { network, unauthorized, forbidden, notFound, rateLimited, unavailable, server, invalid }

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
      kind == ApiErrorKind.rateLimited;

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

  ApiException _unreachable() => ApiException(ApiErrorKind.network,
      "Can't reach the campus server at $_host. Make sure this tablet is connected to the campus Wi-Fi.");

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

  Future<Student> me() async =>
      Student.fromMe(_map(await _request('GET', '/api/v1/me')));

  Future<List<SubjectItem>> subjects() async =>
      _list(await _request('GET', '/api/v1/subjects')).map(SubjectItem.fromJson).toList();

  Future<List<ChapterItem>> chapters(String subjectId) async =>
      _list(await _request('GET', '/api/v1/subjects/$subjectId/chapters')).map(ChapterItem.fromJson).toList();

  Future<List<VideoItem>> videos(String chapterId) async =>
      _list(await _request('GET', '/api/v1/chapters/$chapterId/videos')).map(VideoItem.fromJson).toList();

  Future<List<RecentItem>> recent({int limit = 10, bool includeCompleted = true}) async => _list(
          await _request('GET', '/api/v1/me/recent?limit=$limit&include_completed=$includeCompleted'))
      .map(RecentItem.fromJson)
      .toList();

  Future<PlaybackInfo> authorizePlayback(String videoId) async =>
      PlaybackInfo.fromJson(_map(await _request('POST', '/api/v1/videos/$videoId/playback')));

  Future<Progress> saveProgress(
    String videoId, {
    required int positionSeconds,
    int? durationSeconds,
    bool completed = false,
  }) async =>
      Progress.fromJson(_map(await _request('PUT', '/api/v1/videos/$videoId/progress', body: {
        'position_seconds': positionSeconds,
        'duration_seconds': ?durationSeconds,
        'is_completed': completed,
      })));

  void close() => _http.close();
}
