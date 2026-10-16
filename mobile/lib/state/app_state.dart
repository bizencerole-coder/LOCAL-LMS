import 'dart:convert';

import 'package:flutter/widgets.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../api/api_client.dart';
import '../api/models.dart';
import '../config.dart';

/// App-wide state: server address, signed-in student, and server reachability.
///
/// The session token lives in Android's encrypted storage; the server address
/// and a cached copy of the student's name live in shared preferences so the
/// app can open straight to the home screen without a network round trip.
class AppState extends ChangeNotifier {
  AppState._(this._prefs, this._secure, this._serverUrl, this._token, this._student) {
    _api = _buildClient();
  }

  static const _kServerUrl = 'server_url';
  static const _kStudent = 'student';
  static const _kToken = 'session_token';

  final SharedPreferences _prefs;
  final FlutterSecureStorage _secure;
  String _serverUrl;
  String? _token;
  Student? _student;
  late ApiClient _api;

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
    return AppState._(prefs, secure, serverUrl, student == null ? null : token, student);
  }

  String get serverUrl => _serverUrl;
  Student? get student => _student;
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
