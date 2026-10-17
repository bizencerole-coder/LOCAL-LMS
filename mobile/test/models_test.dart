import 'dart:convert';

import 'package:campus_lms/api/models.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  group('Student', () {
    test('login gives the class and batch names', () {
      final student = Student.fromLogin(
          {'id': 'u1', 'full_name': 'Demo Student', 'class_name': 'Class 12', 'batch_name': '2026-27'});
      expect(student.batchName, '2026-27');
      expect(student.groupLabel, '2026-27 · Class 12');
    });

    test('login from a server without batches', () {
      final student = Student.fromLogin({'id': 'u1', 'full_name': 'Demo Student', 'class_name': 'Class 12'});
      expect(student.batchName, isNull);
      expect(student.groupLabel, 'Class 12');
    });

    test('/me reads the class and batch objects, either of which may be null', () {
      final full = Student.fromMe({
        'id': 'u1',
        'student_code': 'DEMO-12-001',
        'username': 'demo.student',
        'full_name': 'Demo Student',
        'class': {'id': 'k1', 'name': 'Class 12'},
        'batch': {'id': 'b1', 'name': '2026-27'},
      });
      expect(full.className, 'Class 12');
      expect(full.batchName, '2026-27');

      final none = Student.fromMe({'id': 'u1', 'full_name': 'Demo Student', 'class': null, 'batch': null});
      expect(none.className, isNull);
      expect(none.batchName, isNull);
      expect(none.groupLabel, '');
    });

    test('a profile cached by app 1.0 (no batch_name) still loads', () {
      final cached = jsonDecode('{"id":"u1","full_name":"Demo Student","class_name":"Class 12",'
          '"username":"demo.student","student_code":"DEMO-12-001"}') as Map<String, dynamic>;
      final student = Student.fromJson(cached);
      expect(student.fullName, 'Demo Student');
      expect(student.batchName, isNull);
      expect(student.groupLabel, 'Class 12');
    });

    test('the cached copy keeps the batch', () {
      const student = Student(id: 'u1', fullName: 'Demo Student', className: 'Class 12', batchName: '2026-27');
      final restored = Student.fromJson(jsonDecode(jsonEncode(student.toJson())) as Map<String, dynamic>);
      expect(restored.batchName, '2026-27');
      expect(restored.className, 'Class 12');
    });
  });

  test('ContentType.parse knows video, pdf and image; anything else is unknown', () {
    expect(ContentType.parse('video'), ContentType.video);
    expect(ContentType.parse('pdf'), ContentType.pdf);
    expect(ContentType.parse('Image'), ContentType.image);
    expect(ContentType.parse('quiz'), ContentType.unknown);
    expect(ContentType.parse(''), ContentType.unknown);
    expect(ContentType.parse(null), ContentType.unknown);
    expect(ContentType.parse(3), ContentType.unknown);
  });

  test('SubjectItem ignores the legacy chapter_count and defaults missing counts to 0', () {
    final subject = SubjectItem.fromJson({'id': 's1', 'name': 'Mathematics', 'chapter_count': 3});
    expect(subject.moduleCount, 0);
    expect([subject.contentCount, subject.videoCount, subject.notesCount, subject.imageCount], [0, 0, 0, 0]);
    expect(subject.description, isNull);
  });

  test('a blank description counts as none', () {
    final module = ModuleItem.fromJson({'id': 'm1', 'title': 'Calculus', 'description': '  '});
    expect(module.description, isNull);
  });

  group('ContentItem', () {
    test('only id, type and title are required', () {
      final item = ContentItem.fromJson({'id': 'c1', 'type': 'pdf', 'title': 'Notes'});
      expect(item.type, ContentType.pdf);
      expect(item.moduleId, isNull);
      expect(item.description, isNull);
      expect(item.sortOrder, 0);
      expect(item.durationSeconds, isNull);
      expect(item.fileSizeBytes, isNull);
      expect(item.progress, isNull);
      expect(item.isCompleted, isFalse);
      expect(item.moduleTitle, isNull);
    });

    test('a type from a newer server is kept as unknown instead of failing the list', () {
      final item = ContentItem.fromJson({
        'id': 'q1',
        'module_id': 'm1',
        'type': 'interactive_quiz',
        'title': 'Quick quiz',
        'duration_seconds': 300,
        'progress': {'content_id': 'q1', 'position_seconds': 0, 'is_completed': false},
      });
      expect(item.type, ContentType.unknown);
      expect(item.title, 'Quick quiz');
      expect(item.progress!.contentId, 'q1');
    });

    test('progress tolerates missing and malformed optional values', () {
      final progress = Progress.fromJson({
        'content_id': 'v1',
        'position_seconds': 120.0,
        'is_completed': null,
        'last_watched_at': 'yesterday',
      });
      expect(progress.positionSeconds, 120);
      expect(progress.durationSeconds, isNull);
      expect(progress.isCompleted, isFalse);
      expect(progress.lastWatchedAt, isNull);
      expect(progress.fraction(null), isNull);
      expect(progress.fraction(480), 0.25);
    });
  });

  test('ContentAccess: optional fields may be null', () {
    final access = ContentAccess.fromJson({
      'content_id': 'n1',
      'type': 'pdf',
      'title': 'Python Basics: Notes',
      'url': 'http://lms/media/n.pdf?md5=m',
      'expires_at': '2026-10-16T15:00:00Z',
      'mime_type': 'application/pdf',
      'duration_seconds': null,
      'file_size_bytes': null,
      'resume_position_seconds': 0,
      'is_completed': true,
    });
    expect(access.type, ContentType.pdf);
    expect(access.durationSeconds, isNull);
    expect(access.fileSizeBytes, isNull);
    expect(access.isCompleted, isTrue);
  });

  test('ContinueItem falls back to the names inside the content object', () {
    final item = ContinueItem.fromJson({
      'content': {
        'id': 'n1',
        'type': 'pdf',
        'title': 'Python Basics: Notes',
        'module_title': 'Python Basics',
        'subject_name': 'Computer Science',
      },
    });
    expect(item.moduleTitle, 'Python Basics');
    expect(item.subjectName, 'Computer Science');
    expect(item.location, 'Computer Science › Python Basics');

    final bare = ContinueItem.fromJson({
      'content': {'id': 'n1', 'type': 'pdf', 'title': 'Notes'},
      'module_title': 'Python Basics',
    });
    expect(bare.location, 'Python Basics');
  });
}
