import 'dart:convert';

import 'package:flutter/widgets.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../api/api_client.dart';
import '../api/models.dart';
import '../config.dart';

/// App-wide state: server address, signed-in student, the school's branding, the
/// unread-notice count and server reachability.
///
/// The session token lives in Android's encrypted storage; the server address and
/// cached copies of the student's name and the school's branding live in shared
/// preferences so the app opens straight to its screens without a network round trip.
class AppState extends ChangeNotifier {
  AppState._(this._prefs, this._secure, this._serverUrl, this._token, this._student, this._school) {
    _api = _buildClient();
  }

  static const _kServerUrl = 'server_url';
  static const _kStudent = 'student';
  static const _kToken = 'session_token';
  static const _kSchool = 'school_profile';

  /// Newest notice the student has seen, per student (tablets may be shared).
  static String _kNoticesSeen(String studentId) => 'notices_seen_$studentId';

  final SharedPreferences _prefs;
  final FlutterSecureStorage _secure;
  String _serverUrl;
  String? _token;
  Student? _student;
  SchoolProfile _school;
  late ApiClient _api;

  /// Notices published since the student last opened the Notices tab.
  final ValueNotifier<int> unreadNotices = ValueNotifier(0);

  /// null = not checked yet.
  final ValueNotifier<bool?> serverReachable = ValueNotifier(null);

  static Future<AppState> load() async {
    final prefs = await SharedPreferences.getInstance();
    const secure = FlutterSecureStorage();
    final serverUrl = prefs.getString(_kServerUrl) ?? normalizeServerUrl(AppConfig.defaultServerUrl);
    String? token;
    try {
      token = await secure.read(key: _kToken);
    } catch (_) {
      token = null; // Keystore problems: just ask the student to sign in again.
    }
    Student? student;
    final cached = prefs.getString(_kStudent);
    if (token != null && cached != null) {
      student = Student.fromJson(jsonDecode(cached) as Map<String, dynamic>);
    }
    var school = SchoolProfile.fallback;
    final cachedSchool = prefs.getString(_kSchool);
    if (cachedSchool != null) {
      try {
        school = SchoolProfile.fromJson(jsonDecode(cachedSchool) as Map<String, dynamic>);
      } catch (_) {}
    }
    return AppState._(prefs, secure, serverUrl, student == null ? null : token, student, school);
  }

  String get serverUrl => _serverUrl;
  Student? get student => _student;
  SchoolProfile get school => _school;
  bool get isSignedIn => _token != null && _student != null;
  ApiClient get api => _api;

  ApiClient _buildClient() => ApiClient(
        baseUrl: _serverUrl,
        token: _token,
        onUnauthorized: _handleUnauthorized,
        onReachability: (ok) => serverReachable.value = ok,
      );

  /// A client for a server address that has not been saved yet (connection test).
  ApiClient clientFor(String serverUrl) => ApiClient(baseUrl: serverUrl);

  Future<void> setServerUrl(String url) async {
    final normalized = tryNormalizeServerUrl(url);
    if (normalized == null) throw ArgumentError.value(url, 'url', 'Invalid server address');
    if (normalized == _serverUrl) return;
    await _clearSession();
    _serverUrl = normalized;
    await _prefs.setString(_kServerUrl, normalized);
    _rebuildClient();
    notifyListeners();
  }

  Future<void> signIn(String username, String password) async {
    final result = await _api.login(username.trim(), password);
    // Persist before changing in-memory state. If the device's keystore is
    // unavailable the session still works until the app restarts.
    try {
      await _secure.write(key: _kToken, value: result.token);
      await _prefs.setString(_kStudent, jsonEncode(result.student.toJson()));
    } catch (_) {}
    _token = result.token;
    _student = result.student;
    _rebuildClient();
    notifyListeners();
  }

  /// Signs out locally even if the server cannot be reached.
  Future<void> signOut() async {
    if (_token != null) {
      try {
        await _api.logout();
      } on ApiException {
        // Offline or already expired: the local session is removed regardless.
      }
    }
    await _clearSession();
    _rebuildClient();
    notifyListeners();
  }

  /// Refreshes the cached profile; keeps the cached copy if offline.
  Future<void> refreshProfile() async {
    if (!isSignedIn) return;
    try {
      final me = await _api.me();
      _student = me;
      await _prefs.setString(_kStudent, jsonEncode(me.toJson()));
      notifyListeners();
    } on ApiException {
      // Unauthorized is handled by _handleUnauthorized; other errors are shown by screens.
    }
  }

  /// Fetches the school's name, colour and logo; keeps the cached copy when the server
  /// cannot be reached (or is older than app 1.2 and has no branding).
  Future<void> refreshSchool() async {
    try {
      final school = await _api.school();
      await _prefs.setString(_kSchool, jsonEncode(school.toJson()));
      if (school != _school) {
        _school = school;
        notifyListeners();
      }
    } on ApiException {
      // Keep what we have.
    }
  }

  DateTime? get _noticesSeenAt {
    final id = _student?.id;
    final value = id == null ? null : _prefs.getString(_kNoticesSeen(id));
    return value == null ? null : DateTime.tryParse(value);
  }

  /// Published after the newest notice the student had seen.
  bool isNoticeUnread(NoticeItem notice) {
    final seen = _noticesSeenAt;
    return seen == null || notice.publishedAt.isAfter(seen);
  }

  /// Loads the student's notices and updates [unreadNotices].
  Future<List<NoticeItem>> loadNotices() async {
    final notices = await _api.notices();
    unreadNotices.value = notices.where(isNoticeUnread).length;
    return notices;
  }

  /// The student has now seen [notices] (compared by the server's publication times,
  /// not this tablet's clock).
  Future<void> markNoticesSeen(List<NoticeItem> notices) async {
    final id = _student?.id;
    if (id != null && notices.isNotEmpty) {
      final newest = notices.map((n) => n.publishedAt).reduce((a, b) => a.isAfter(b) ? a : b);
      final seen = _noticesSeenAt;
      if (seen == null || newest.isAfter(seen)) {
        await _prefs.setString(_kNoticesSeen(id), newest.toUtc().toIso8601String());
      }
    }
    unreadNotices.value = 0;
  }

  void _handleUnauthorized() {
    if (_token == null) return;
    _clearSession().then((_) {
      _rebuildClient();
      notifyListeners();
    });
  }

  Future<void> _clearSession() async {
    _token = null;
    _student = null;
    unreadNotices.value = 0;
    await _prefs.remove(_kStudent);
    try {
      await _secure.delete(key: _kToken);
    } catch (_) {}
  }

  void _rebuildClient() {
    _api.close();
    _api = _buildClient();
  }
}

/// Makes [AppState] available to the widget tree.
class AppScope extends InheritedNotifier<AppState> {
  const AppScope({super.key, required AppState state, required super.child}) : super(notifier: state);

  /// Rebuilds the caller when the state changes.
  static AppState of(BuildContext context) =>
      context.dependOnInheritedWidgetOfExactType<AppScope>()!.notifier!;

  /// Reads the state without subscribing (for callbacks).
  static AppState read(BuildContext context) =>
      context.getInheritedWidgetOfExactType<AppScope>()!.notifier!;
}
