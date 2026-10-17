import 'package:flutter/material.dart';

import '../api/models.dart';
import '../state/app_state.dart';
import '../util/format.dart';
import '../widgets/catalog_style.dart';
import '../widgets/content_tile.dart';
import '../widgets/layout.dart';
import '../widgets/states.dart';
import 'open_content.dart';

/// Everything in one module (videos, notes and images) in teaching order.
class ModuleScreen extends StatefulWidget {
  const ModuleScreen({super.key, required this.subject, required this.module});

  final SubjectItem subject;
  final ModuleItem module;

  @override
  State<ModuleScreen> createState() => _ModuleScreenState();
}

class _ModuleScreenState extends State<ModuleScreen> {
  final _loaderKey = GlobalKey<LoaderState<List<ContentItem>>>();

  @override
  Widget build(BuildContext context) {
    final location = '${widget.subject.name} › ${widget.module.title}';
    return Scaffold(
      appBar: AppBar(title: Text(widget.module.title)),
      body: Loader<List<ContentItem>>(
        key: _loaderKey,
        load: () => AppScope.read(context).api.contents(widget.module.id),
        builder: (context, contents, reload) => RefreshIndicator(
          onRefresh: reload,
          child: LayoutBuilder(
            builder: (context, constraints) => ListView(
              padding: readablePadding(constraints.maxWidth),
              children: [
                _ModuleHeader(subject: widget.subject, module: widget.module, contents: contents),
                const SizedBox(height: 20),
                if (contents.isEmpty)
                  const Padding(
                    padding: EdgeInsets.only(top: 32),
                    child: MessageView(icon: Icons.folder_open_outlined, title: 'Nothing in this module yet'),
                  )
                else
                  for (final item in contents)
                    ContentTile(
                      content: item,
                      onTap: () async {
                        await openContentItem(context, item, subtitle: location);
                        // A video returns after its final progress save, notes and images after the
                        // server recorded them as opened, so the reloaded list shows both.
                        _loaderKey.currentState?.reload();
                      },
                    ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

/// Subject, module title, description, what the module holds and how far the student
/// got (from the loaded items, so it is current after closing one).
class _ModuleHeader extends StatelessWidget {
  const _ModuleHeader({required this.subject, required this.module, required this.contents});

  final SubjectItem subject;
  final ModuleItem module;
  final List<ContentItem> contents;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final color = subjectColor(subject.name);
    final brightness = theme.brightness;
    int count(ContentType type) => contents.where((item) => item.type == type).length;
    final counts = contentCounts(
      videos: count(ContentType.video),
      notes: count(ContentType.pdf),
      images: count(ContentType.image),
      total: contents.length,
    );
    final completed = contents.where((item) => item.isCompleted).length;
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
                SubjectBadge(name: subject.name, size: 48, background: theme.colorScheme.surface),
                const SizedBox(width: 16),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(subject.name,
                          style: theme.textTheme.labelLarge?.copyWith(color: inkOf(color, brightness))),
                      const SizedBox(height: 2),
                      Text(module.title, style: theme.textTheme.headlineSmall),
                      if (counts.isNotEmpty) ...[
                        const SizedBox(height: 4),
                        Text(counts, style: theme.textTheme.bodyMedium),
                      ],
                    ],
                  ),
                ),
              ],
            ),
            if (module.description != null) ...[
              const SizedBox(height: 16),
              Text(module.description!, style: theme.textTheme.bodyLarge),
            ],
            if (contents.isNotEmpty) ...[
              const SizedBox(height: 16),
              CompletionBar(completed: completed, total: contents.length, color: color),
            ],
          ],
        ),
      ),
    );
  }
}
