/// Build-time and runtime defaults.
///
/// The server address can be changed in the app (login screen → Server) and is
/// remembered. Set a different default at build time with:
///   flutter build apk --dart-define=LMS_SERVER_URL=http://192.168.10.10
class AppConfig {
  static const defaultServerUrl = String.fromEnvironment(
    'LMS_SERVER_URL',
    defaultValue: 'http://192.168.10.10',
  );

  static const requestTimeout = Duration(seconds: 10);

  /// How often progress is saved while a video plays (PRD FR-07: 15–30 s).
  static const progressSaveInterval = Duration(seconds: 20);

  /// Time allowed for the player to open a video before showing an error.
  static const playerStartTimeout = Duration(seconds: 30);
}
