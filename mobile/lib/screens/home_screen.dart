import 'package:flutter/material.dart';

import '../api/models.dart';
import '../state/app_state.dart';
import '../util/format.dart';
import '../widgets/connection_indicator.dart';
import '../widgets/states.dart';
import 'chapters_screen.dart';
import 'my_learning_screen.dart';
import 'player_screen.dart';

class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  int _tab = 0;
  final _subjectsKey = GlobalKey<LoaderState<_HomeData>>();
  final _learningKey = GlobalKey<LoaderState<List<RecentItem>>>();

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
                  subtitle: Text([student?.className, student?.studentCode].nonNulls.join(' · ')),
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
  final List<RecentItem> continueWatching;
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
          api.recent(limit: 10, includeCompleted: false),
        ]);
        return _HomeData(results[0] as List<SubjectItem>, results[1] as List<RecentItem>);
      },
      builder: (context, data, reload) {
        final theme = Theme.of(context);
        return RefreshIndicator(
          onRefresh: reload,
          child: ListView(
            padding: const EdgeInsets.all(24),
            children: [
              Text('Hello, ${student?.fullName ?? ''}', style: theme.textTheme.headlineSmall),
              if (student?.className != null) Text(student!.className!, style: theme.textTheme.bodyLarge),
              if (data.continueWatching.isNotEmpty) ...[
                const SizedBox(height: 24),
                Text('Continue watching', style: theme.textTheme.titleLarge),
                const SizedBox(height: 12),
                SizedBox(
                  // Card content scales with the system font size.
                  height: 52 + MediaQuery.textScalerOf(context).scale(80),
                  child: ListView.separated(
                    scrollDirection: Axis.horizontal,
                    itemCount: data.continueWatching.length,
                    separatorBuilder: (_, _) => const SizedBox(width: 12),
                    itemBuilder: (context, i) => _ContinueCard(item: data.continueWatching[i], onReturn: onReturn),
                  ),
                ),
              ],
              const SizedBox(height: 24),
              Text('Subjects', style: theme.textTheme.titleLarge),
              const SizedBox(height: 12),
              if (data.subjects.isEmpty)
                const MessageView(
                  icon: Icons.inbox_outlined,
                  title: 'No subjects yet',
                  message: 'Lessons assigned to your class will appear here.',
                )
              else
                GridView.builder(
                  shrinkWrap: true,
                  physics: const NeverScrollableScrollPhysics(),
                  gridDelegate: SliverGridDelegateWithMaxCrossAxisExtent(
                    maxCrossAxisExtent: 320,
                    mainAxisExtent: 40 + MediaQuery.textScalerOf(context).scale(80),
                    crossAxisSpacing: 12,
                    mainAxisSpacing: 12,
                  ),
                  itemCount: data.subjects.length,
                  itemBuilder: (context, i) => _SubjectCard(subject: data.subjects[i], onReturn: onReturn),
                ),
            ],
          ),
        );
      },
    );
  }
}

class _SubjectCard extends StatelessWidget {
  const _SubjectCard({required this.subject, required this.onReturn});

  final SubjectItem subject;
  final VoidCallback onReturn;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Card(
      clipBehavior: Clip.antiAlias,
      child: InkWell(
        onTap: () async {
          await Navigator.of(context).push(MaterialPageRoute(builder: (_) => ChaptersScreen(subject: subject)));
          onReturn();
        },
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Text(subject.name, style: theme.textTheme.titleMedium, maxLines: 2, overflow: TextOverflow.ellipsis),
              Text(
                '${plural(subject.chapterCount, 'chapter')} · ${plural(subject.videoCount, 'lesson')}',
                style: theme.textTheme.bodySmall,
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _ContinueCard extends StatelessWidget {
  const _ContinueCard({required this.item, required this.onReturn});

  final RecentItem item;
  final VoidCallback onReturn;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final video = item.video;
    final fraction = video.progress?.fraction(video.durationSeconds);
    return SizedBox(
      width: 280,
      child: Card(
        clipBehavior: Clip.antiAlias,
        child: InkWell(
          onTap: () async {
            await openLesson(context,
                videoId: video.id, title: video.title, subtitle: '${item.subjectName} › ${item.chapterTitle}');
            onReturn();
          },
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(item.subjectName, style: theme.textTheme.labelMedium, maxLines: 1, overflow: TextOverflow.ellipsis),
                const SizedBox(height: 4),
                Text(video.title, style: theme.textTheme.titleSmall, maxLines: 2, overflow: TextOverflow.ellipsis),
                const Spacer(),
                Row(children: [
                  const Icon(Icons.play_circle_outline, size: 18),
                  const SizedBox(width: 6),
                  Expanded(
                    child: Text('Resume at ${formatSeconds(video.progress?.positionSeconds)}',
                        style: theme.textTheme.bodySmall, maxLines: 1, overflow: TextOverflow.ellipsis),
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
