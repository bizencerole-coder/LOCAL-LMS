import 'package:flutter/material.dart';

import '../api/models.dart';
import '../state/app_state.dart';
import '../widgets/content_tile.dart';
import '../widgets/layout.dart';
import '../widgets/states.dart';
import 'open_content.dart';

/// Recently watched videos and opened notes and images, newest first, with how far
/// the student got (PRD 10.5).
class MyLearningTab extends StatelessWidget {
  const MyLearningTab({super.key, required this.loaderKey, required this.onReturn});

  final GlobalKey<LoaderState<List<ContinueItem>>> loaderKey;
  final VoidCallback onReturn;

  @override
  Widget build(BuildContext context) {
    return Loader<List<ContinueItem>>(
      key: loaderKey,
      load: () => AppScope.read(context).api.continueItems(limit: 50, includeCompleted: true),
      builder: (context, items, reload) => RefreshIndicator(
        onRefresh: reload,
        child: items.isEmpty
            ? ListView(children: const [
                SizedBox(height: 80),
                MessageView(
                  icon: Icons.history_toggle_off,
                  title: 'Nothing opened yet',
                  message: 'Videos, notes and images you open will appear here so you can pick up where you left off.',
                ),
              ])
            : LayoutBuilder(
                builder: (context, constraints) => ListView.builder(
                  padding: readablePadding(constraints.maxWidth),
                  itemCount: items.length,
                  itemBuilder: (context, i) {
                    final item = items[i];
                    return ContentTile(
                      content: item.content,
                      subtitle: item.location,
                      onTap: () async {
                        await openContentItem(context, item.content, subtitle: item.location);
                        onReturn();
                      },
                    );
                  },
                ),
              ),
      ),
    );
  }
}
