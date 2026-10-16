import 'package:flutter/material.dart';

import '../api/models.dart';
import '../state/app_state.dart';
import '../widgets/lesson_tile.dart';
import '../widgets/states.dart';
import 'player_screen.dart';

/// Recently watched lessons with their saved position (PRD 10.5).
class MyLearningTab extends StatelessWidget {
  const MyLearningTab({super.key, required this.loaderKey, required this.onReturn});

  final GlobalKey<LoaderState<List<RecentItem>>> loaderKey;
  final VoidCallback onReturn;

  @override
  Widget build(BuildContext context) {
    return Loader<List<RecentItem>>(
      key: loaderKey,
      load: () => AppScope.read(context).api.recent(limit: 50),
      builder: (context, items, reload) => RefreshIndicator(
        onRefresh: reload,
        child: items.isEmpty
            ? ListView(children: const [
                SizedBox(height: 80),
                MessageView(
                  icon: Icons.history_toggle_off,
                  title: 'Nothing watched yet',
                  message: 'Lessons you start will appear here so you can pick up where you left off.',
                ),
              ])
            : ListView.builder(
                padding: const EdgeInsets.all(24),
                itemCount: items.length,
                itemBuilder: (context, i) {
                  final item = items[i];
                  final subtitle = '${item.subjectName} › ${item.chapterTitle}';
                  return LessonTile(
                    video: item.video,
                    subtitle: subtitle,
                    onTap: () async {
                      await openLesson(context, videoId: item.video.id, title: item.video.title, subtitle: subtitle);
                      onReturn();
                    },
                  );
                },
              ),
      ),
    );
  }
}
