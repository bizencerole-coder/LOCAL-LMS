/// Data returned by the Campus LMS API (see docs/api.md).
library;

class Student {
  const Student({
    required this.id,
    required this.fullName,
    this.className,
    this.username,
    this.studentCode,
  });

  final String id;
  final String fullName;
  final String? className;
  final String? username;
  final String? studentCode;

  /// From the login response's `student` object.
  factory Student.fromLogin(Map<String, dynamic> json) => Student(
        id: json['id'] as String,
        fullName: json['full_name'] as String,
        className: json['class_name'] as String?,
      );

  /// From `GET /api/v1/me`.
  factory Student.fromMe(Map<String, dynamic> json) {
    final schoolClass = json['class'] as Map<String, dynamic>?;
    return Student(
      id: json['id'] as String,
      fullName: json['full_name'] as String,
      className: schoolClass?['name'] as String?,
      username: json['username'] as String?,
      studentCode: json['student_code'] as String?,
    );
  }

  /// Local cache format (shared preferences).
  Map<String, dynamic> toJson() => {
        'id': id,
        'full_name': fullName,
        'class_name': className,
        'username': username,
        'student_code': studentCode,
      };

  factory Student.fromJson(Map<String, dynamic> json) => Student(
        id: json['id'] as String,
        fullName: json['full_name'] as String,
        className: json['class_name'] as String?,
        username: json['username'] as String?,
        studentCode: json['student_code'] as String?,
      );
}

class LoginResult {
  const LoginResult({required this.token, required this.student, required this.expiresIn});

  final String token;
  final Student student;
  final Duration expiresIn;
}

class SubjectItem {
  const SubjectItem({
    required this.id,
    required this.name,
    required this.chapterCount,
    required this.videoCount,
  });

  final String id;
  final String name;
  final int chapterCount;
  final int videoCount;

  factory SubjectItem.fromJson(Map<String, dynamic> json) => SubjectItem(
        id: json['id'] as String,
        name: json['name'] as String,
        chapterCount: json['chapter_count'] as int? ?? 0,
        videoCount: json['video_count'] as int? ?? 0,
      );
}

class ChapterItem {
  const ChapterItem({
    required this.id,
    required this.title,
    this.description,
    required this.videoCount,
  });

  final String id;
  final String title;
  final String? description;
  final int videoCount;

  factory ChapterItem.fromJson(Map<String, dynamic> json) => ChapterItem(
        id: json['id'] as String,
        title: json['title'] as String,
        description: json['description'] as String?,
        videoCount: json['video_count'] as int? ?? 0,
      );
}

class Progress {
  const Progress({
    required this.positionSeconds,
    this.durationSeconds,
    required this.isCompleted,
    this.lastWatchedAt,
  });

  final int positionSeconds;
  final int? durationSeconds;
  final bool isCompleted;
  final DateTime? lastWatchedAt;

  /// 0.0–1.0, or null when the duration is unknown.
  double? fraction(int? videoDuration) {
    final total = videoDuration ?? durationSeconds;
    if (total == null || total <= 0) return null;
    return (positionSeconds / total).clamp(0.0, 1.0);
  }

  factory Progress.fromJson(Map<String, dynamic> json) => Progress(
        positionSeconds: json['position_seconds'] as int? ?? 0,
        durationSeconds: json['duration_seconds'] as int?,
        isCompleted: json['is_completed'] as bool? ?? false,
        lastWatchedAt: json['last_watched_at'] == null
            ? null
            : DateTime.parse(json['last_watched_at'] as String),
      );
}

class VideoItem {
  const VideoItem({
    required this.id,
    required this.title,
    this.description,
    this.durationSeconds,
    this.progress,
  });

  final String id;
  final String title;
  final String? description;
  final int? durationSeconds;
  final Progress? progress;

  factory VideoItem.fromJson(Map<String, dynamic> json) => VideoItem(
        id: json['id'] as String,
        title: json['title'] as String,
        description: json['description'] as String?,
        durationSeconds: json['duration_seconds'] as int?,
        progress: json['progress'] == null
            ? null
            : Progress.fromJson(json['progress'] as Map<String, dynamic>),
      );
}

class RecentItem {
  const RecentItem({required this.video, required this.chapterTitle, required this.subjectName});

  final VideoItem video;
  final String chapterTitle;
  final String subjectName;

  factory RecentItem.fromJson(Map<String, dynamic> json) => RecentItem(
        video: VideoItem.fromJson(json['video'] as Map<String, dynamic>),
        chapterTitle: json['chapter_title'] as String,
        subjectName: json['subject_name'] as String,
      );
}

class PlaybackInfo {
  const PlaybackInfo({
    required this.videoId,
    required this.title,
    required this.url,
    required this.expiresAt,
    this.durationSeconds,
    required this.resumePositionSeconds,
    required this.isCompleted,
  });

  final String videoId;
  final String title;
  final Uri url;
  final DateTime expiresAt;
  final int? durationSeconds;
  final int resumePositionSeconds;
  final bool isCompleted;

  factory PlaybackInfo.fromJson(Map<String, dynamic> json) => PlaybackInfo(
        videoId: json['video_id'] as String,
        title: json['title'] as String,
        url: Uri.parse(json['playback_url'] as String),
        expiresAt: DateTime.parse(json['expires_at'] as String),
        durationSeconds: json['duration_seconds'] as int?,
        resumePositionSeconds: json['resume_position_seconds'] as int? ?? 0,
        isCompleted: json['is_completed'] as bool? ?? false,
      );
}
