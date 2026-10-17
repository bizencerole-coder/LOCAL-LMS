/// Data returned by the Campus LMS API (see docs/api.md).
library;

// Optional fields are read leniently: a missing or oddly typed value becomes null
// (or 0 for counts) instead of failing the whole list.
int? _int(Object? value) => value is num ? value.toInt() : null;

/// A non-blank string, or null.
String? _text(Object? value) => value is String && value.trim().isNotEmpty ? value : null;

DateTime? _date(Object? value) => value is String ? DateTime.tryParse(value) : null;

class Student {
  const Student({
    required this.id,
    required this.fullName,
    this.className,
    this.batchName,
    this.username,
    this.studentCode,
  });

  final String id;
  final String fullName;
  final String? className;
  final String? batchName;
  final String? username;
  final String? studentCode;

  /// "Batch 2026 · Class 12", or whichever of the two is known ('' if neither).
  String get groupLabel => [batchName, className].nonNulls.join(' · ');

  /// From the login response's `student` object.
  factory Student.fromLogin(Map<String, dynamic> json) => Student(
        id: json['id'] as String,
        fullName: json['full_name'] as String,
        className: _text(json['class_name']),
        batchName: _text(json['batch_name']),
      );

  /// From `GET /api/v1/me`.
  factory Student.fromMe(Map<String, dynamic> json) {
    final schoolClass = json['class'];
    final batch = json['batch'];
    return Student(
      id: json['id'] as String,
      fullName: json['full_name'] as String,
      className: schoolClass is Map ? _text(schoolClass['name']) : null,
      batchName: batch is Map ? _text(batch['name']) : null,
      username: json['username'] as String?,
      studentCode: json['student_code'] as String?,
    );
  }

  /// Local cache format (shared preferences).
  Map<String, dynamic> toJson() => {
        'id': id,
        'full_name': fullName,
        'class_name': className,
        'batch_name': batchName,
        'username': username,
        'student_code': studentCode,
      };

  /// Reads [toJson]'s format. Copies cached by app 1.0 have no `batch_name`.
  factory Student.fromJson(Map<String, dynamic> json) => Student(
        id: json['id'] as String,
        fullName: json['full_name'] as String,
        className: json['class_name'] as String?,
        batchName: json['batch_name'] as String?,
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
    this.description,
    this.sortOrder = 0,
    this.moduleCount = 0,
    this.contentCount = 0,
    this.videoCount = 0,
    this.notesCount = 0,
    this.imageCount = 0,
    this.completedCount = 0,
  });

  final String id;
  final String name;
  final String? description;
  final int sortOrder;
  final int moduleCount;
  final int contentCount;
  final int videoCount;
  final int notesCount;
  final int imageCount;

  /// How many of [contentCount] this student has completed (0 from servers before 1.1).
  final int completedCount;

  /// The legacy `chapter_count` the server still sends for app 1.0 is ignored.
  factory SubjectItem.fromJson(Map<String, dynamic> json) => SubjectItem(
        id: json['id'] as String,
        name: json['name'] as String,
        description: _text(json['description']),
        sortOrder: _int(json['sort_order']) ?? 0,
        moduleCount: _int(json['module_count']) ?? 0,
        contentCount: _int(json['content_count']) ?? 0,
        videoCount: _int(json['video_count']) ?? 0,
        notesCount: _int(json['notes_count']) ?? 0,
        imageCount: _int(json['image_count']) ?? 0,
        completedCount: _int(json['completed_count']) ?? 0,
      );
}

class ModuleItem {
  const ModuleItem({
    required this.id,
    required this.title,
    this.subjectId,
    this.description,
    this.sortOrder = 0,
    this.contentCount = 0,
    this.videoCount = 0,
    this.notesCount = 0,
    this.imageCount = 0,
    this.completedCount = 0,
  });

  final String id;
  final String title;
  final String? subjectId;
  final String? description;
  final int sortOrder;
  final int contentCount;
  final int videoCount;
  final int notesCount;
  final int imageCount;

  /// How many of [contentCount] this student has completed (0 from servers before 1.1).
  final int completedCount;

  factory ModuleItem.fromJson(Map<String, dynamic> json) => ModuleItem(
        id: json['id'] as String,
        title: json['title'] as String,
        subjectId: json['subject_id'] as String?,
        description: _text(json['description']),
        sortOrder: _int(json['sort_order']) ?? 0,
        contentCount: _int(json['content_count']) ?? 0,
        videoCount: _int(json['video_count']) ?? 0,
        notesCount: _int(json['notes_count']) ?? 0,
        imageCount: _int(json['image_count']) ?? 0,
        completedCount: _int(json['completed_count']) ?? 0,
      );
}

/// What a content item is. Students see `pdf` items as "Notes".
enum ContentType {
  video,
  pdf,
  image,

  /// A type added on the server after this version of the app; listed but not opened.
  unknown;

  static ContentType parse(Object? value) => switch (value is String ? value.trim().toLowerCase() : null) {
        'video' => ContentType.video,
        'pdf' => ContentType.pdf,
        'image' => ContentType.image,
        _ => ContentType.unknown,
      };
}

class Progress {
  const Progress({
    this.contentId,
    required this.positionSeconds,
    this.durationSeconds,
    required this.isCompleted,
    this.lastWatchedAt,
  });

  final String? contentId;
  final int positionSeconds;
  final int? durationSeconds;
  final bool isCompleted;
  final DateTime? lastWatchedAt;

  /// 0.0–1.0, or null when the duration is unknown.
  double? fraction(int? contentDuration) {
    final total = contentDuration ?? durationSeconds;
    if (total == null || total <= 0) return null;
    return (positionSeconds / total).clamp(0.0, 1.0);
  }

  factory Progress.fromJson(Map<String, dynamic> json) => Progress(
        contentId: json['content_id'] as String?,
        positionSeconds: _int(json['position_seconds']) ?? 0,
        durationSeconds: _int(json['duration_seconds']),
        isCompleted: json['is_completed'] == true,
        lastWatchedAt: _date(json['last_watched_at']),
      );
}

/// One item in a module: a video, notes (PDF), an image, or a type this app does not know.
class ContentItem {
  const ContentItem({
    required this.id,
    required this.type,
    required this.title,
    this.moduleId,
    this.description,
    this.sortOrder = 0,
    this.durationSeconds,
    this.fileSizeBytes,
    this.progress,
    this.moduleTitle,
    this.subjectId,
    this.subjectName,
  });

  final String id;
  final ContentType type;
  final String title;
  final String? moduleId;
  final String? description;
  final int sortOrder;
  final int? durationSeconds;
  final int? fileSizeBytes;

  /// null when the student has not opened the item yet.
  final Progress? progress;

  /// Only sent by `GET /contents/{id}`.
  final String? moduleTitle;
  final String? subjectId;
  final String? subjectName;

  bool get isCompleted => progress?.isCompleted ?? false;

  factory ContentItem.fromJson(Map<String, dynamic> json) {
    final progress = json['progress'];
    return ContentItem(
      id: json['id'] as String,
      type: ContentType.parse(json['type']),
      title: json['title'] as String,
      moduleId: json['module_id'] as String?,
      description: _text(json['description']),
      sortOrder: _int(json['sort_order']) ?? 0,
      durationSeconds: _int(json['duration_seconds']),
      fileSizeBytes: _int(json['file_size_bytes']),
      progress: progress is Map<String, dynamic> ? Progress.fromJson(progress) : null,
      moduleTitle: _text(json['module_title']),
      subjectId: json['subject_id'] as String?,
      subjectName: _text(json['subject_name']),
    );
  }
}

/// `POST /contents/{id}/open`: a short-lived signed URL for the item's file on the
/// campus server (fetched without the Authorization header), and where a video resumes.
class ContentAccess {
  const ContentAccess({
    required this.contentId,
    required this.type,
    required this.title,
    required this.url,
    required this.expiresAt,
    this.mimeType,
    this.durationSeconds,
    this.fileSizeBytes,
    this.resumePositionSeconds = 0,
    this.isCompleted = false,
  });

  final String contentId;
  final ContentType type;
  final String title;
  final Uri url;
  final DateTime expiresAt;
  final String? mimeType;
  final int? durationSeconds;
  final int? fileSizeBytes;
  final int resumePositionSeconds;
  final bool isCompleted;

  /// [base] resolves a URL given relative to the server (normally it is absolute).
  factory ContentAccess.fromJson(Map<String, dynamic> json, {Uri? base}) {
    final url = Uri.parse(json['url'] as String);
    return ContentAccess(
      contentId: json['content_id'] as String,
      type: ContentType.parse(json['type']),
      title: json['title'] as String? ?? '',
      url: base == null ? url : base.resolveUri(url),
      expiresAt: DateTime.parse(json['expires_at'] as String),
      mimeType: json['mime_type'] as String?,
      durationSeconds: _int(json['duration_seconds']),
      fileSizeBytes: _int(json['file_size_bytes']),
      resumePositionSeconds: _int(json['resume_position_seconds']) ?? 0,
      isCompleted: json['is_completed'] == true,
    );
  }
}

/// An entry of `GET /me/continue`: a recently watched or opened item and where it lives.
class ContinueItem {
  const ContinueItem({required this.content, required this.moduleTitle, required this.subjectName});

  final ContentItem content;
  final String moduleTitle;
  final String subjectName;

  /// "Computer Science › Python Basics".
  String get location => [subjectName, moduleTitle].where((part) => part.isNotEmpty).join(' › ');

  factory ContinueItem.fromJson(Map<String, dynamic> json) {
    final content = ContentItem.fromJson(json['content'] as Map<String, dynamic>);
    return ContinueItem(
      content: content,
      moduleTitle: _text(json['module_title']) ?? content.moduleTitle ?? '',
      subjectName: _text(json['subject_name']) ?? content.subjectName ?? '',
    );
  }
}
