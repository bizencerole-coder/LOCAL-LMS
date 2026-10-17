import 'dart:convert';

import 'package:campus_lms/api/api_client.dart';
import 'package:campus_lms/api/models.dart';
import 'package:campus_lms/screens/login_screen.dart';
import 'package:campus_lms/state/app_state.dart';
import 'package:campus_lms/theme.dart';
import 'package:campus_lms/util/format.dart';
import 'package:campus_lms/widgets/banner_carousel.dart';
import 'package:campus_lms/widgets/brand.dart';
import 'package:campus_lms/widgets/greeting_card.dart';
import 'package:campus_lms/widgets/notice_tile.dart';
import 'package:flutter/material.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:shared_preferences/shared_preferences.dart';

http.Response jsonResponse(Object body, [int status = 200]) =>
    http.Response(jsonEncode(body), status, headers: {'content-type': 'application/json'});

const _student = {'id': 's1', 'full_name': 'Anu Krishnan', 'class_name': 'Class 12', 'batch_name': 'Batch 2026-27'};

/// An app state for a signed-in student, without touching the network.
Future<AppState> signedInState({Map<String, Object> prefs = const {}}) async {
  SharedPreferences.setMockInitialValues({'server_url': 'http://lms', 'student': jsonEncode(_student), ...prefs});
  FlutterSecureStorage.setMockInitialValues({'session_token': 't'});
  return AppState.load();
}

Widget host(AppState state, Widget child) =>
    AppScope(state: state, child: MaterialApp(home: Scaffold(body: SingleChildScrollView(child: child))));

NoticeItem notice(String id, String publishedAt, {bool important = false}) => NoticeItem(
      id: id,
      title: 'Notice $id',
      body: 'Details of notice $id',
      publishedAt: DateTime.parse(publishedAt),
      isImportant: important,
      audience: 'All students',
    );

void main() {
  group('models', () {
    test('school profile: defaults, a checked colour, and the cache format', () {
      final school = SchoolProfile.fromJson({
        'name': 'Riverside Public School',
        'short_name': 'Riverside',
        'tagline': '  ',
        'primary_color': '#1e3a8a',
        'logo_url': '/branding/logo-1.png',
      });
      expect((school.displayName, school.tagline, school.primaryColor), ('Riverside', null, '#1e3a8a'));
      expect(SchoolProfile.fromJson(school.toJson()), school);
      final odd = SchoolProfile.fromJson({'name': '', 'primary_color': 'teal'});
      expect((odd.name, odd.displayName, odd.primaryColor), ('Campus LMS', 'Campus LMS', null));
    });

    test('notices and banners are read leniently; links the app cannot open are dropped', () {
      final n = NoticeItem.fromJson({
        'id': 'n1',
        'title': 'Unit test on Monday',
        'body': null,
        'is_important': true,
        'published_at': '2026-10-17T04:00:00Z',
        'audience': 'Batch 2026-27 › Class 12',
      });
      expect((n.isImportant, n.body, n.publishedAt.isUtc), (true, null, true));

      BannerItem banner(Object? link) =>
          BannerItem.fromJson({'id': 'b', 'title': 'Slide', 'subtitle': null, 'image_url': null, 'link': link});
      expect(banner(null).link, isNull);
      expect(banner({'type': 'quiz', 'id': 'q', 'title': 'Quiz'}).link, isNull);
      expect(banner({'type': 'module', 'id': 'm', 'title': 'Motion'}).link, isNull, reason: 'no subject_id');
      final module = banner({'type': 'module', 'id': 'm', 'title': 'Motion', 'subject_id': 'p'}).link!;
      expect((module.type, module.subjectId), (BannerLinkType.module, 'p'));
    });
  });

  test('the school profile needs no sign-in; notices and banners do', () async {
    final auth = <String, String?>{};
    final api = ApiClient(
      baseUrl: 'http://lms',
      token: 't',
      httpClient: MockClient((request) async {
        auth[request.url.path] = request.headers['Authorization'];
        return switch (request.url.path) {
          '/api/v1/school' => jsonResponse({
              'name': 'Riverside Public School',
              'short_name': null,
              'tagline': 'Learn anywhere on campus',
              'primary_color': '#1E3A8A',
              'logo_url': '/branding/logo-1.png',
              'updated_at': null,
            }),
          '/api/v1/notices' => jsonResponse([
              {'id': 'n1', 'title': 'Holiday', 'body': 'Friday', 'is_important': false,
               'published_at': '2026-10-17T04:00:00Z', 'expires_at': null, 'audience': 'All students'},
            ]),
          '/api/v1/banners' => jsonResponse([
              {'id': 'b1', 'title': 'Welcome', 'subtitle': null, 'image_url': '/branding/banner-1.jpg', 'link': null},
            ]),
          _ => jsonResponse({}, 404),
        };
      }),
    );
    final school = await api.school();
    expect(school.displayName, 'Riverside Public School');
    expect(api.resolve(school.logoUrl!).toString(), 'http://lms/branding/logo-1.png');
    expect((await api.notices()).single.title, 'Holiday');
    expect((await api.banners()).single.imageUrl, '/branding/banner-1.jpg');
    expect(auth['/api/v1/school'], isNull);
    expect(auth['/api/v1/notices'], 'Bearer t');
    expect(auth['/api/v1/banners'], 'Bearer t');
  });

  group('colours and words', () {
    test('school colours, and a light one darkened for white text', () {
      expect(brandColor('#1E3A8A'), const Color(0xFF1E3A8A));
      expect(brandColor('teal'), defaultBrandColor);
      expect(brandColor(null), defaultBrandColor);
      final (start, end) = heroColors(const Color(0xFFFFE066));
      expect(start.computeLuminance(), lessThan(0.3));
      expect(end.computeLuminance(), lessThan(start.computeLuminance()));
      expect(heroColors(const Color(0xFF1E3A8A)).$1, const Color(0xFF1E3A8A));
    });

    test('greetings, initials and dates', () {
      expect(greetingFor(DateTime(2026, 10, 17, 9)), 'Good morning');
      expect(greetingFor(DateTime(2026, 10, 17, 13)), 'Good afternoon');
      expect(greetingFor(DateTime(2026, 10, 17, 19)), 'Good evening');
      expect(firstNameOf('Anu Krishnan'), 'Anu');
      expect(initialsOf('Demo Student'), 'DS');
      expect(initialsOf('School of Arts'), 'SA');
      expect(initialsOf("St. Mary's HSS"), 'SH');
      expect(initialsOf('Riverside'), 'R');
      expect(formatDayHeading(DateTime(2026, 10, 17)), 'Saturday, 17 October');

      final now = DateTime(2026, 10, 17, 12);
      String ago(Duration d) => formatRelativeTime(now.subtract(d), now: now);
      expect(ago(const Duration(seconds: 30)), 'Just now');
      expect(ago(const Duration(minutes: 12)), '12 min ago');
      expect(ago(const Duration(hours: 3)), '3 h ago');
      expect(ago(const Duration(hours: 16)), 'Yesterday');
      expect(ago(const Duration(days: 4)), '4 days ago');
      expect(ago(const Duration(days: 20)), '27 Sep 2026');
    });
  });

  group('app state', () {
    test('notices are new until the student opens them, compared by server time', () async {
      final state = await signedInState();
      final a = notice('a', '2026-10-17T05:00:00Z');
      final b = notice('b', '2026-10-17T06:00:00Z');
      expect(state.isNoticeUnread(a), isTrue);
      state.unreadNotices.value = 2;
      await state.markNoticesSeen([a, b]);
      expect(state.unreadNotices.value, 0);
      expect(state.isNoticeUnread(a) || state.isNoticeUnread(b), isFalse);
      expect(state.isNoticeUnread(notice('c', '2026-10-17T06:30:00Z')), isTrue);
      // Kept for the next start of the app.
      expect((await AppState.load()).isNoticeUnread(b), isFalse);
    });

    test('the school profile is cached for the next start', () async {
      final cached = const SchoolProfile(name: 'Riverside Public School', primaryColor: '#1E3A8A').toJson();
      final state = await signedInState(prefs: {'school_profile': jsonEncode(cached)});
      expect((state.school.name, state.school.primaryColor), ('Riverside Public School', '#1E3A8A'));
    });
  });

  group('widgets', () {
    testWidgets('the greeting uses the first name, the date, the class and progress', (tester) async {
      final state = await signedInState();
      await tester.pumpWidget(host(
        state,
        GreetingCard(student: state.student, inProgress: 2, completed: 5, total: 12, now: DateTime(2026, 10, 17, 9, 30)),
      ));
      expect(find.text('Good morning, Anu'), findsOneWidget);
      expect(find.text('Saturday, 17 October'), findsOneWidget);
      expect(find.text('Batch 2026-27 · Class 12'), findsOneWidget);
      expect(find.text('5 / 12'), findsOneWidget);
      expect(find.text('In progress'), findsOneWidget);
    });

    testWidgets('banner slides move on by themselves, show dots, and open their link', (tester) async {
      final semantics = tester.ensureSemantics();
      final state = await signedInState();
      final opened = <String>[];
      await tester.pumpWidget(host(
        state,
        BannerCarousel(
          interval: const Duration(seconds: 3),
          onOpen: (banner) => opened.add(banner.id),
          banners: const [
            BannerItem(id: '1', title: 'Revision starts Monday', subtitle: 'Daily videos in every subject'),
            BannerItem(
              id: '2',
              title: 'New in Computer Science',
              link: BannerLink(type: BannerLinkType.subject, id: 'cs', title: 'Computer Science'),
            ),
          ],
        ),
      ));
      expect(find.text('Revision starts Monday'), findsOneWidget);
      expect(find.bySemanticsLabel('Slide 1 of 2'), findsOneWidget);
      await tester.tap(find.text('Revision starts Monday'));
      expect(opened, isEmpty, reason: 'a slide without a link opens nothing');

      await tester.pump(const Duration(seconds: 3));
      await tester.pumpAndSettle();
      expect(find.bySemanticsLabel('Slide 2 of 2'), findsOneWidget);
      expect(find.text('Open subject'), findsOneWidget);
      await tester.tap(find.text('New in Computer Science'));
      expect(opened, ['2']);

      await tester.pumpWidget(const SizedBox()); // stops the slide timer
      semantics.dispose();
    });

    testWidgets('notice tiles show important and new notices', (tester) async {
      final state = await signedInState();
      final semantics = tester.ensureSemantics();
      await tester.pumpWidget(host(
        state,
        Column(children: [
          NoticeTile(notice: notice('a', '2026-10-17T05:00:00Z', important: true), unread: true),
          NoticeTile(notice: notice('b', '2026-10-17T04:00:00Z')),
        ]),
      ));
      expect(find.text('Notice a'), findsOneWidget);
      expect(find.text('Important'), findsOneWidget);
      String spoken(Finder tile) => tester.getSemantics(tile).getSemanticsData().label;
      expect(spoken(find.byType(NoticeTile).first), allOf(contains('Notice a'), contains('New')));
      expect(spoken(find.byType(NoticeTile).last), isNot(contains('New')));
      expect(find.text('All students'), findsNWidgets(2));
      semantics.dispose();
    });

    testWidgets('without a logo the school shows its initials', (tester) async {
      final state = await signedInState(
          prefs: {'school_profile': jsonEncode(const SchoolProfile(name: 'Riverside Public School').toJson())});
      await tester.pumpWidget(host(state, const SchoolLogo(size: 48)));
      expect(find.text('RS'), findsOneWidget);
    });
  });

  group('fits on a phone with large text', () {
    for (final (name, size) in const [('phone', Size(360, 760)), ('tablet', Size(1280, 800))]) {
      testWidgets('sign-in screen ($name)', (tester) async {
        tester.view.physicalSize = size * 2;
        tester.view.devicePixelRatio = 2;
        addTearDown(tester.view.reset);
        final state = await signedInState();
        await tester.pumpWidget(AppScope(
          state: state,
          child: MaterialApp(
            builder: (context, child) => MediaQuery(
              data: MediaQuery.of(context).copyWith(textScaler: const TextScaler.linear(1.3)),
              child: child!,
            ),
            home: const LoginScreen(),
          ),
        ));
        await tester.pump();
        expect(tester.takeException(), isNull);
        expect(find.text('Welcome back'), findsOneWidget);
        expect(find.text('Campus LMS'), findsOneWidget, reason: 'school name before the server answers');
      });
    }

    testWidgets('greeting card', (tester) async {
      tester.view.physicalSize = const Size(360, 760) * 2;
      tester.view.devicePixelRatio = 2;
      addTearDown(tester.view.reset);
      final state = await signedInState();
      await tester.pumpWidget(AppScope(
        state: state,
        child: MaterialApp(
          builder: (context, child) => MediaQuery(
            data: MediaQuery.of(context).copyWith(textScaler: const TextScaler.linear(1.5)),
            child: child!,
          ),
          home: Scaffold(
            body: SingleChildScrollView(
              child: GreetingCard(student: state.student, inProgress: 12, completed: 120, total: 340),
            ),
          ),
        ),
      ));
      expect(tester.takeException(), isNull);
    });
  });
}
