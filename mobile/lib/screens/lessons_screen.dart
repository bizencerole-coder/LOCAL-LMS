import 'package:flutter/material.dart';

import '../api/models.dart';
import '../state/app_state.dart';
import '../widgets/lesson_tile.dart';
import '../widgets/states.dart';
import 'player_screen.dart';

class LessonsScreen extends StatefulWidget {
  const LessonsScreen({super.key, required this.subject, required this.chapter});

  final SubjectItem subject;
  final ChapterItem chapter;

  @override
  State<LessonsScreen> createState() => _LessonsScreenState();
}

class _LessonsScreenState extends State<LessonsScreen> {
  final _loaderKey = GlobalKey<LoaderState<List<VideoItem>>>();

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text(widget.chapter.title)),
      body: Loader<List<VideoItem>>(
        key: _loaderKey,
        load: () => AppScope.read(context).api.videos(widget.chapter.id),
        builder: (context, videos, reload) => RefreshIndicator(
          onRefresh: reload,
          child: videos.isEmpty
              ? ListView(children: const [
                  SizedBox(height: 80),
                  MessageView(icon: Icons.video_library_outlined, title: 'No lessons in this chapter yet'),
                ])
              : ListView.builder(
                  padding: const EdgeInsets.all(24),
                  itemCount: videos.length,
                  itemBuilder: (context, i) => LessonTile(
                    video: videos[i],
                    onTap: () async {
                      await openLesson(context,
                          videoId: videos[i].id,
                          title: videos[i].title,
                          subtitle: '${widget.subject.name} › ${widget.chapter.title}');
                      // openLesson returns after the final progress save, so the list shows it.
                      _loaderKey.currentState?.reload();
                    },
                  ),
                ),
        ),
      ),
    );
  }
}
