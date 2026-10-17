# Campus LMS — Android app

Flutter app for students: sign in, browse subjects → modules → content (videos, notes and
images), watch, read, resume. Talks only to the campus LMS server; no Firebase, analytics,
remote fonts or internet checks.

## Build

Requires Flutter 3.44+ (Dart 3.12) and the Android SDK (`flutter doctor`).

```bash
cd mobile
flutter pub get
flutter test && flutter analyze

# Debug build (quick, larger)
flutter build apk --debug

# Release build for tablets; set the default server address shown on first launch
flutter build apk --release --dart-define=LMS_SERVER_URL=http://192.168.10.10
```

Output: `build/app/outputs/flutter-apk/app-release.apk`. The prototype release build is
signed with the debug key (fine for side-loading test tablets; set up a real signing key
before any wider distribution).

On Windows, if the project and the Flutter pub cache are on different drives, Kotlin
incremental compilation fails; `android/gradle.properties` already sets
`kotlin.incremental=false` for that reason.

## Install on a tablet

1. Enable *Developer options → USB debugging* (or allow installing unknown apps).
2. `adb install -r build/app/outputs/flutter-apk/app-release.apk`, or copy the APK over and open it.
3. Launch **Campus LMS** → tap **Server:** → enter the server address → **Test connection** → **Save**.
4. Sign in with a student account.

Minimum Android version: 7.0 (API 24).

## Structure

| Path | What |
|---|---|
| `lib/api/` | HTTP client, error mapping, file downloads, JSON models |
| `lib/state/app_state.dart` | Server address, session (token in Android encrypted storage), reachability |
| `lib/screens/` | Login, Home (Subjects, Continue Watching), My Learning, Subject (modules), Module (content), Player, Notes and Image viewers; `open_content.dart` picks the screen for a content type |
| `lib/player/` | Player controls (`player_view.dart`) and progress saving (`progress_reporter.dart`) |
| `lib/widgets/` | Loading/error/empty states, content tile and type icons, connection indicator |

## Content types

The server's hierarchy is Batch → Class → Subject → Module → Content. Each content item is a
`video`, a `pdf` (shown to students as **Notes**) or an `image`. A type added on the server
later is listed with a file icon and "This item can't be opened in this version of the app."

## Player behaviour

- `POST /api/v1/contents/{id}/open` returns a signed URL; the video streams directly from Nginx.
- Resumes 3 s before the saved position (starts over if the lesson was finished);
  a snackbar offers **Start over**.
- Saves progress every 20 s while playing, on pause, when leaving the screen or the app,
  and at the end. A failed save never interrupts playback; a failed completion save is
  re-sent until it succeeds. Back waits for the final save before the previous screen
  reloads, so lists show the new position.
- When the signed URL expires mid-lesson the player fetches a fresh one and continues
  from the same position automatically; other playback errors show **Try again**.
- A lesson opened while the tablet is being locked or switched away from does not start
  playing in the background; it starts when the app is back in front.
- Keeps the screen awake only while playing. Full-screen is landscape + immersive, and
  the system bars are restored on exit on every Android version.

## Notes and images

- Opening notes or an image calls the same `/open` endpoint (the server records the item as
  opened) and downloads the file once from its signed URL: up to 100 MB, giving up after 10 s
  without data or 60 s overall (longer for big files). An expired link (403/410) is replaced
  automatically once; other failures show **Try again**, which asks for a fresh link.
- Notes render on the tablet with Android's PdfRenderer through `pdfx` (pinned), from a private
  temporary copy that is deleted as soon as it is open: page indicator, pinch zoom, portrait and
  landscape, no network or CDN needed. Images show with pinch and double-tap zoom.

The player uses the Flutter team's `video_player` package (Android Media3/ExoPlayer).
This is the prototype choice and must be validated on the target tablets (PRD §6.2); the
player code is confined to `lib/player/` and `lib/screens/player_screen.dart` so it can be
swapped for `media_kit` if needed.

## Prototype limitations

- HTTP only (`android:usesCleartextTraffic="true"`), acceptable only on an isolated campus
  network. Remove it when local TLS is introduced.
- Android only; no iOS build.
