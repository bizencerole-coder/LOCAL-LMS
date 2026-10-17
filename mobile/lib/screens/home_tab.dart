import 'dart:math' as math;

import 'package:flutter/material.dart';

import '../api/api_client.dart';
import '../api/models.dart';
import '../state/app_state.dart';
import '../util/format.dart';
import '../widgets/banner_carousel.dart';
import '../widgets/brand.dart';
import '../widgets/continue_card.dart';
import '../widgets/greeting_card.dart';
import '../widgets/layout.dart';
import '../widgets/notice_tile.dart';
import '../widgets/states.dart';
import '../widgets/subject_card.dart';
import 'module_screen.dart';
import 'notices_screen.dart';
import 'subject_screen.dart';

class _HomeData {
  const _HomeData({
    required this.subjects,
    required this.continueWatching,
    required this.banners,
    required this.notices,
  });

  final List<SubjectItem> subjects;
  final List<ContinueItem> continueWatching;
  final List<BannerItem> banners;
  final List<NoticeItem> notices;
}

/// Servers older than app 1.2 have no banners or notices: the rest of the page still works.
Future<List<T>> _optional<T>(Future<List<T>> request) async {
  try {
    return await request;
  } on ApiException catch (e) {
    if (e.kind == ApiErrorKind.notFound) return <T>[];
    rethrow;
  }
}

/// How many subjects the home page shows before "See all".
const homeSubjectLimit = 6;

/// The Home tab: greeting, the school's banner, the latest notices, Continue watching
/// and the student's subjects.
class HomeTab extends StatefulWidget {
  const HomeTab({
    super.key,
    required this.onReturn,
    required this.onSeeAllSubjects,
    required this.onSeeAllNotices,
  });

  /// After coming back from a lesson: progress may have changed everywhere.
  final VoidCallback onReturn;
  final VoidCallback onSeeAllSubjects;
  final VoidCallback onSeeAllNotices;

  @override
  State<HomeTab> createState() => HomeTabState();
}

class HomeTabState extends State<HomeTab> {
  final _loaderKey = GlobalKey<LoaderState<_HomeData>>();

  void reload() => _loaderKey.currentState?.reload();

  Future<_HomeData> _load() async {
    final state = AppScope.read(context);
    final api = state.api; // the current client, not the one at build time
    final results = await Future.wait<Object>([
      api.subjects(),
      api.continueItems(limit: 10, includeCompleted: false),
      _optional(api.banners()),
      _optional(state.loadNotices()),
    ]);
    return _HomeData(
      subjects: results[0] as List<SubjectItem>,
      continueWatching: results[1] as List<ContinueItem>,
      banners: results[2] as List<BannerItem>,
      notices: results[3] as List<NoticeItem>,
    );
  }

  Future<void> _openBanner(_HomeData data, BannerItem banner) async {
    final link = banner.link;
    if (link == null) return;
    final api = AppScope.read(context).api;
    final navigator = Navigator.of(context);
    final messenger = ScaffoldMessenger.of(context);
    void unavailable() =>
        messenger.showSnackBar(const SnackBar(content: Text('This is no longer available.')));
    try {
      switch (link.type) {
        case BannerLinkType.notice:
          var notice = data.notices.where((n) => n.id == link.id).firstOrNull;
          notice ??= (await api.notices(limit: 200)).where((n) => n.id == link.id).firstOrNull;
          if (notice == null) {
            unavailable();
            return;
          }
          await navigator.push(MaterialPageRoute(builder: (_) => NoticeScreen(notice: notice!)));
        case BannerLinkType.subject:
          final subject = data.subjects.where((s) => s.id == link.id).firstOrNull;
          if (subject == null) {
            unavailable();
            return;
          }
          await navigator.push(MaterialPageRoute(builder: (_) => SubjectScreen(subject: subject)));
        case BannerLinkType.module:
          final subject = data.subjects.where((s) => s.id == link.subjectId).firstOrNull;
          final module = subject == null
              ? null
              : (await api.modules(subject.id)).where((m) => m.id == link.id).firstOrNull;
          if (subject == null || module == null) {
            unavailable();
            return;
          }
          await navigator.push(MaterialPageRoute(builder: (_) => ModuleScreen(subject: subject, module: module)));
      }
      widget.onReturn();
    } on ApiException catch (e) {
      messenger.showSnackBar(SnackBar(content: Text(e.message)));
    }
  }

  @override
  Widget build(BuildContext context) {
    final state = AppScope.of(context);
    final student = state.student;
    final school = state.school;
    return Loader<_HomeData>(
      key: _loaderKey,
      load: _load,
      builder: (context, data, reload) {
        final completed = data.subjects.fold<int>(0, (sum, s) => sum + s.completedCount);
        final total = data.subjects.fold<int>(0, (sum, s) => sum + s.contentCount);
        final banners = data.banners.isNotEmpty
            ? data.banners
            : [
                BannerItem(
                  id: 'welcome',
                  title: 'Welcome to ${school.name}',
                  subtitle: school.tagline ?? 'Your lessons, notes and notices in one place.',
                ),
              ];
        return RefreshIndicator(
          onRefresh: () => Future.wait([reload(), state.refreshSchool()]),
          child: LayoutBuilder(
            builder: (context, constraints) => ListView(
              padding: readablePadding(constraints.maxWidth, gutter: 20),
              children: [
                GreetingCard(
                  student: student,
                  inProgress: data.continueWatching.length,
                  completed: completed,
                  total: total,
                ),
                const SizedBox(height: 20),
                BannerCarousel(banners: banners, onOpen: (banner) => _openBanner(data, banner)),
                if (data.notices.isNotEmpty) ...[
                  const SizedBox(height: 28),
                  SectionHeader(
                    title: 'Notices',
                    subtitle: 'Latest from ${school.displayName}',
                    onAction: widget.onSeeAllNotices,
                  ),
                  // Rebuilds when the Notices tab marks them as seen.
                  ValueListenableBuilder<int>(
                    valueListenable: state.unreadNotices,
                    builder: (context, _, _) => Column(
                      children: [
                        for (final notice in data.notices.take(3))
                          NoticeTile(
                            notice: notice,
                            unread: state.isNoticeUnread(notice),
                            onTap: () => openNotice(context, notice),
                          ),
                      ],
                    ),
                  ),
                ],
                if (data.continueWatching.isNotEmpty) ...[
                  const SizedBox(height: 28),
                  const SectionHeader(title: 'Continue watching'),
                  SizedBox(
                    height: ContinueCard.height(context),
                    child: ListView.separated(
                      scrollDirection: Axis.horizontal,
                      itemCount: data.continueWatching.length,
                      separatorBuilder: (_, _) => const SizedBox(width: 12),
                      itemBuilder: (context, i) =>
                          ContinueCard(item: data.continueWatching[i], onReturn: widget.onReturn),
                    ),
                  ),
                ],
                const SizedBox(height: 28),
                SectionHeader(
                  title: 'Your subjects',
                  subtitle: data.subjects.isEmpty ? null : plural(data.subjects.length, 'subject'),
                  onAction: data.subjects.length > homeSubjectLimit ? widget.onSeeAllSubjects : null,
                ),
                if (data.subjects.isEmpty)
                  const MessageView(
                    icon: Icons.inbox_outlined,
                    title: 'No subjects yet',
                    message: 'Subjects for your class will appear here.',
                  )
                else
                  GridView.builder(
                    shrinkWrap: true,
                    physics: const NeverScrollableScrollPhysics(),
                    gridDelegate: SliverGridDelegateWithMaxCrossAxisExtent(
                      maxCrossAxisExtent: 320,
                      mainAxisExtent: SubjectCard.height(context),
                      crossAxisSpacing: 12,
                      mainAxisSpacing: 8,
                    ),
                    itemCount: math.min(homeSubjectLimit, data.subjects.length),
                    itemBuilder: (context, i) => SubjectCard(subject: data.subjects[i], onReturn: widget.onReturn),
                  ),
              ],
            ),
          ),
        );
      },
    );
  }
}
