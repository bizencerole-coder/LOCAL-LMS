import 'package:flutter/material.dart';

import '../api/models.dart';
import '../state/app_state.dart';
import '../util/format.dart';
import '../widgets/catalog_style.dart';
import '../widgets/layout.dart';
import '../widgets/states.dart';
import 'module_screen.dart';

/// The modules of one subject, in teaching order, with how far the student got.
class SubjectScreen extends StatefulWidget {
  const SubjectScreen({super.key, required this.subject});

  final SubjectItem subject;

  @override
  State<SubjectScreen> createState() => _SubjectScreenState();
}

class _SubjectScreenState extends State<SubjectScreen> {
  final _loaderKey = GlobalKey<LoaderState<List<ModuleItem>>>();

  @override
  Widget build(BuildContext context) {
    final subject = widget.subject;
    return Scaffold(
      appBar: AppBar(title: Text(subject.name)),
      body: Loader<List<ModuleItem>>(
        key: _loaderKey,
        load: () => AppScope.read(context).api.modules(subject.id),
        builder: (context, modules, reload) => RefreshIndicator(
          onRefresh: reload,
          child: LayoutBuilder(
            builder: (context, constraints) => ListView(
              padding: readablePadding(constraints.maxWidth),
              children: [
                _SubjectHeader(subject: subject, modules: modules),
                const SizedBox(height: 24),
                if (modules.isEmpty)
                  const Padding(
                    padding: EdgeInsets.only(top: 32),
                    child: MessageView(
                      icon: Icons.folder_open_outlined,
                      title: 'No modules yet',
                      message: 'Modules added to this subject will appear here.',
                    ),
                  )
                else ...[
                  Text('Modules', style: Theme.of(context).textTheme.titleLarge),
                  const SizedBox(height: 12),
                  for (final (i, module) in modules.indexed)
                    _ModuleCard(
                      number: i + 1,
                      subjectName: subject.name,
                      module: module,
                      onTap: () async {
                        await Navigator.of(context).push(MaterialPageRoute<void>(
                          builder: (_) => ModuleScreen(subject: subject, module: module),
                        ));
                        // Progress made in the module shows up here straight away.
                        _loaderKey.currentState?.reload();
                      },
                    ),
                ],
              ],
            ),
          ),
        ),
      ),
    );
  }
}

/// The subject's name, description, what it holds and the student's progress in it
/// (added up from the modules, so it is current after returning from one).
class _SubjectHeader extends StatelessWidget {
  const _SubjectHeader({required this.subject, required this.modules});

  final SubjectItem subject;
  final List<ModuleItem> modules;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final color = subjectColor(subject.name);
    final brightness = theme.brightness;
    var total = 0, completed = 0, videos = 0, notes = 0, images = 0;
    for (final module in modules) {
      total += module.contentCount;
      completed += module.completedCount;
      videos += module.videoCount;
      notes += module.notesCount;
      images += module.imageCount;
    }
    final counts = contentCounts(videos: videos, notes: notes, images: images, total: total);
    final summary = [if (modules.isNotEmpty) plural(modules.length, 'module'), if (counts.isNotEmpty) counts].join(' · ');
    return Card(
      elevation: 0,
      color: tintOf(color, brightness),
      child: Padding(
        padding: const EdgeInsets.all(20),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                SubjectBadge(name: subject.name, size: 56, background: theme.colorScheme.surface),
                const SizedBox(width: 16),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(subject.name, style: theme.textTheme.headlineSmall),
                      if (summary.isNotEmpty) ...[
                        const SizedBox(height: 4),
                        Text(summary,
                            style: theme.textTheme.bodyMedium?.copyWith(color: inkOf(color, brightness))),
                      ],
                    ],
                  ),
                ),
              ],
            ),
            if (subject.description != null) ...[
              const SizedBox(height: 16),
              Text(subject.description!, style: theme.textTheme.bodyLarge),
            ],
            if (total > 0) ...[
              const SizedBox(height: 16),
              CompletionBar(completed: completed, total: total, color: color),
            ],
          ],
        ),
      ),
    );
  }
}

class _ModuleCard extends StatelessWidget {
  const _ModuleCard({required this.number, required this.subjectName, required this.module, required this.onTap});

  final int number;
  final String subjectName;
  final ModuleItem module;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final scheme = theme.colorScheme;
    final counts = contentCounts(
      videos: module.videoCount,
      notes: module.notesCount,
      images: module.imageCount,
      total: module.contentCount,
    );
    return Card(
      margin: const EdgeInsets.symmetric(vertical: 6),
      clipBehavior: Clip.antiAlias,
      child: InkWell(
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.fromLTRB(16, 16, 12, 16),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              SubjectBadge(name: subjectName, size: 44, child: Text('$number')),
              const SizedBox(width: 16),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(module.title, style: theme.textTheme.titleMedium),
                    const SizedBox(height: 2),
                    Text(counts.isEmpty ? 'Nothing here yet' : counts,
                        style: theme.textTheme.bodySmall?.copyWith(color: scheme.onSurfaceVariant)),
                    if (module.description != null) ...[
                      const SizedBox(height: 6),
                      Text(module.description!, style: theme.textTheme.bodyMedium),
                    ],
                    if (module.contentCount > 0) ...[
                      const SizedBox(height: 12),
                      CompletionBar(
                        completed: module.completedCount,
                        total: module.contentCount,
                        color: subjectColor(subjectName),
                      ),
                    ],
                  ],
                ),
              ),
              const SizedBox(width: 8),
              Padding(
                padding: const EdgeInsets.only(top: 10),
                child: Icon(Icons.chevron_right_rounded, color: scheme.onSurfaceVariant),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
