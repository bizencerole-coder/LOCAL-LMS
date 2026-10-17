import 'dart:math' as math;

import 'package:flutter/material.dart';

import '../api/models.dart';
import '../state/app_state.dart';
import '../util/format.dart';
import '../widgets/catalog_style.dart';
import '../widgets/connection_indicator.dart';
import '../widgets/content_tile.dart';
import '../widgets/layout.dart';
import '../widgets/states.dart';
import 'my_learning_screen.dart';
import 'open_content.dart';
import 'subject_screen.dart';

class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  int _tab = 0;
  final _subjectsKey = GlobalKey<LoaderState<_HomeData>>();
  final _learningKey = GlobalKey<LoaderState<List<ContinueItem>>>();

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => AppScope.read(context).refreshProfile());
  }

  /// Reloads both tabs, e.g. after returning from the player with new progress.
  void _refresh() {
    _subjectsKey.currentState?.reload();
    _learningKey.currentState?.reload();
  }

  Future<void> _confirmSignOut() async {
    final yes = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Sign out?'),
        content: const Text('You will need your password to sign in again.'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Cancel')),
          FilledButton(onPressed: () => Navigator.pop(context, true), child: const Text('Sign out')),
        ],
      ),
    );
    if (yes == true && mounted) await AppScope.read(context).signOut();
  }

  @override
  Widget build(BuildContext context) {
    final student = AppScope.of(context).student;
    final wide = MediaQuery.sizeOf(context).width >= 720;
    final pages = [
      _SubjectsTab(loaderKey: _subjectsKey, onReturn: _refresh),
      MyLearningTab(loaderKey: _learningKey, onReturn: _refresh),
    ];
    const destinations = [
      (Icons.menu_book_outlined, Icons.menu_book, 'Subjects'),
      (Icons.history_outlined, Icons.history, 'My Learning'),
    ];

    return Scaffold(
      appBar: AppBar(
        title: const Text('Campus LMS'),
        actions: [
          const ConnectionIndicator(),
          const SizedBox(width: 8),
          PopupMenuButton<String>(
            tooltip: 'Account',
            icon: const Icon(Icons.account_circle_outlined),
            onSelected: (_) => _confirmSignOut(),
            itemBuilder: (_) => [
              PopupMenuItem(
                enabled: false,
                child: ListTile(
                  contentPadding: EdgeInsets.zero,
                  title: Text(student?.fullName ?? ''),
                  subtitle: Text(
                      [student?.batchName, student?.className, student?.studentCode].nonNulls.join(' · ')),
                ),
              ),
              const PopupMenuDivider(),
              const PopupMenuItem(
                value: 'signout',
                child: ListTile(contentPadding: EdgeInsets.zero, leading: Icon(Icons.logout), title: Text('Sign out')),
              ),
            ],
          ),
          const SizedBox(width: 8),
        ],
      ),
      body: Row(
        children: [
          if (wide)
            NavigationRail(
              selectedIndex: _tab,
              onDestinationSelected: (i) => setState(() => _tab = i),
              labelType: NavigationRailLabelType.all,
              destinations: [
                for (final (icon, selected, label) in destinations)
                  NavigationRailDestination(icon: Icon(icon), selectedIcon: Icon(selected), label: Text(label)),
              ],
            ),
          Expanded(child: IndexedStack(index: _tab, children: pages)),
        ],
      ),
      bottomNavigationBar: wide
          ? null
          : NavigationBar(
              selectedIndex: _tab,
              onDestinationSelected: (i) => setState(() => _tab = i),
              destinations: [
                for (final (icon, selected, label) in destinations)
                  NavigationDestination(icon: Icon(icon), selectedIcon: Icon(selected), label: label),
              ],
            ),
    );
  }
}

class _HomeData {
  const _HomeData(this.subjects, this.continueWatching);

  final List<SubjectItem> subjects;
  final List<ContinueItem> continueWatching;
}

class _SubjectsTab extends StatelessWidget {
  const _SubjectsTab({required this.loaderKey, required this.onReturn});

  final GlobalKey<LoaderState<_HomeData>> loaderKey;
  final VoidCallback onReturn;

  @override
  Widget build(BuildContext context) {
    final student = AppScope.of(context).student;
    return Loader<_HomeData>(
      key: loaderKey,
      load: () async {
        final api = AppScope.read(context).api; // the current client, not the one at build time
        final results = await Future.wait([
          api.subjects(),
          api.continueItems(limit: 10, includeCompleted: false),
        ]);
        return _HomeData(results[0] as List<SubjectItem>, results[1] as List<ContinueItem>);
      },
      builder: (context, data, reload) {
        final theme = Theme.of(context);
        return RefreshIndicator(
          onRefresh: reload,
          child: LayoutBuilder(
            builder: (context, constraints) => ListView(
              padding: readablePadding(constraints.maxWidth),
              children: [
                _WelcomeCard(student: student),
                if (data.continueWatching.isNotEmpty) ...[
                  const SizedBox(height: 28),
                  Text('Continue watching', style: theme.textTheme.titleLarge),
                  const SizedBox(height: 12),
                  SizedBox(
                    height: _ContinueCard.height(context),
                    child: ListView.separated(
                      scrollDirection: Axis.horizontal,
                      itemCount: data.continueWatching.length,
                      separatorBuilder: (_, _) => const SizedBox(width: 8),
                      itemBuilder: (context, i) => _ContinueCard(item: data.continueWatching[i], onReturn: onReturn),
                    ),
                  ),
                ],
                const SizedBox(height: 28),
                Text('Subjects', style: theme.textTheme.titleLarge),
                const SizedBox(height: 12),
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
                      mainAxisExtent: _SubjectCard.height(context),
                      crossAxisSpacing: 8,
                      mainAxisSpacing: 8,
                    ),
                    itemCount: data.subjects.length,
                    itemBuilder: (context, i) => _SubjectCard(subject: data.subjects[i], onReturn: onReturn),
                  ),
              ],
            ),
          ),
        );
      },
    );
  }
}

/// The student's name with their batch and class.
class _WelcomeCard extends StatelessWidget {
  const _WelcomeCard({required this.student});

  final Student? student;

  /// "DS" for "Demo Student".
  static String _initials(String name) {
    final words = name.trim().split(RegExp(r'\s+')).where((word) => word.isNotEmpty).toList();
    if (words.isEmpty) return '';
    final first = words.first.characters.first;
    final last = words.length > 1 ? words.last.characters.first : '';
    return '$first$last'.toUpperCase();
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final scheme = theme.colorScheme;
    final name = student?.fullName ?? '';
    final initials = _initials(name);
    final group = student?.groupLabel ?? '';
    return Card(
      elevation: 0,
      color: scheme.primaryContainer,
      child: Padding(
        padding: const EdgeInsets.all(20),
        child: Row(
          children: [
            CircleAvatar(
              radius: 28,
              backgroundColor: scheme.primary,
              foregroundColor: scheme.onPrimary,
              child: initials.isEmpty ? const Icon(Icons.person_rounded) : Text(initials),
            ),
            const SizedBox(width: 16),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text('Hello, $name',
                      style: theme.textTheme.headlineSmall?.copyWith(color: scheme.onPrimaryContainer)),
                  if (group.isNotEmpty) ...[
                    const SizedBox(height: 4),
                    Text(group, style: theme.textTheme.bodyLarge?.copyWith(color: scheme.onPrimaryContainer)),
                  ],
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _SubjectCard extends StatelessWidget {
  const _SubjectCard({required this.subject, required this.onReturn});

  final SubjectItem subject;
  final VoidCallback onReturn;

  static const _stripe = 6.0;

  /// Room for the stripe, badge row, two lines of name, two of counts and the progress
  /// bar at the student's text size.
  static double height(BuildContext context) {
    final text = Theme.of(context).textTheme;
    return 8 + _stripe + 32 + 44 + 12 + // card margins, stripe, padding, badge row
        textLinesHeight(context, text.titleMedium, 2) +
        6 +
        textLinesHeight(context, text.bodySmall, 2) +
        12 +
        CompletionBar.height(context);
  }

  /// "4 modules · 6 videos · 2 notes".
  String get _summary {
    final counts = contentCounts(
      videos: subject.videoCount,
      notes: subject.notesCount,
      images: subject.imageCount,
      total: subject.contentCount,
    );
    if (subject.moduleCount == 0) return 'No modules yet';
    return [plural(subject.moduleCount, 'module'), if (counts.isNotEmpty) counts].join(' · ');
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final scheme = theme.colorScheme;
    final color = subjectColor(subject.name);
    return Card(
      clipBehavior: Clip.antiAlias,
      child: InkWell(
        onTap: () async {
          await Navigator.of(context).push(MaterialPageRoute(builder: (_) => SubjectScreen(subject: subject)));
          onReturn();
        },
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Container(height: _stripe, color: inkOf(color, theme.brightness)),
            Expanded(
              child: Padding(
                padding: const EdgeInsets.all(16),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      children: [
                        SubjectBadge(name: subject.name, size: 44),
                        const Spacer(),
                        Icon(Icons.chevron_right_rounded, color: scheme.onSurfaceVariant),
                      ],
                    ),
                    const SizedBox(height: 12),
                    Text(subject.name,
                        style: theme.textTheme.titleMedium, maxLines: 2, overflow: TextOverflow.ellipsis),
                    const SizedBox(height: 6),
                    Text(
                      _summary,
                      style: theme.textTheme.bodySmall?.copyWith(color: scheme.onSurfaceVariant),
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                    ),
                    const Spacer(),
                    if (subject.contentCount > 0)
                      CompletionBar(completed: subject.completedCount, total: subject.contentCount, color: color),
                  ],
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _ContinueCard extends StatelessWidget {
  const _ContinueCard({required this.item, required this.onReturn});

  final ContinueItem item;
  final VoidCallback onReturn;

  /// Room for the subject row, two lines of title and the resume line at the student's text size.
  static double height(BuildContext context) {
    final text = Theme.of(context).textTheme;
    return 8 + 32 + // card margins, padding
        math.max(32.0, textLinesHeight(context, text.labelMedium)) +
        10 +
        textLinesHeight(context, text.titleSmall, 2) +
        8 +
        math.max(18.0, textLinesHeight(context, text.bodySmall)) +
        12; // progress bar
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final content = item.content;
    final isVideo = content.type == ContentType.video;
    final fraction = isVideo ? content.progress?.fraction(content.durationSeconds) : null;
    return SizedBox(
      width: 280,
      child: Card(
        clipBehavior: Clip.antiAlias,
        child: InkWell(
          onTap: () async {
            await openContentItem(context, content, subtitle: item.location);
            onReturn();
          },
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(children: [
                  ContentTypeIcon(type: content.type, size: 32),
                  const SizedBox(width: 10),
                  Expanded(
                    child: Text(item.subjectName,
                        style: theme.textTheme.labelMedium, maxLines: 1, overflow: TextOverflow.ellipsis),
                  ),
                ]),
                const SizedBox(height: 10),
                Text(content.title, style: theme.textTheme.titleSmall, maxLines: 2, overflow: TextOverflow.ellipsis),
                const Spacer(),
                Row(children: [
                  Icon(isVideo ? Icons.play_arrow_rounded : Icons.open_in_new_rounded, size: 18),
                  const SizedBox(width: 6),
                  Expanded(
                    child: Text(
                        isVideo
                            ? 'Resume at ${formatSeconds(content.progress?.positionSeconds)}'
                            : ContentTypeStyle.of(content.type).label,
                        style: theme.textTheme.bodySmall,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis),
                  ),
                ]),
                if (fraction != null) ...[
                  const SizedBox(height: 8),
                  LinearProgressIndicator(value: fraction, minHeight: 4, borderRadius: BorderRadius.circular(2)),
                ],
              ],
            ),
          ),
        ),
      ),
    );
  }
}
