import 'package:flutter/material.dart';

import '../api/models.dart';
import '../state/app_state.dart';
import '../util/format.dart';
import '../widgets/states.dart';
import 'lessons_screen.dart';

class ChaptersScreen extends StatelessWidget {
  const ChaptersScreen({super.key, required this.subject});

  final SubjectItem subject;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text(subject.name)),
      body: Loader<List<ChapterItem>>(
        load: () => AppScope.read(context).api.chapters(subject.id),
        builder: (context, chapters, reload) => RefreshIndicator(
          onRefresh: reload,
          child: chapters.isEmpty
              ? ListView(children: const [
                  SizedBox(height: 80),
                  MessageView(icon: Icons.inbox_outlined, title: 'No chapters yet'),
                ])
              : ListView.builder(
                  padding: const EdgeInsets.all(24),
                  itemCount: chapters.length,
                  itemBuilder: (context, i) {
                    final chapter = chapters[i];
                    return Card(
                      margin: const EdgeInsets.symmetric(vertical: 4),
                      child: ListTile(
                        contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
                        leading: CircleAvatar(child: Text('${i + 1}')),
                        title: Text(chapter.title),
                        subtitle: Text([
                          plural(chapter.videoCount, 'lesson'),
                          if (chapter.description != null && chapter.description!.isNotEmpty) chapter.description!,
                        ].join(' · ')),
                        trailing: const Icon(Icons.chevron_right_rounded),
                        onTap: () => Navigator.of(context).push(MaterialPageRoute(
                          builder: (_) => LessonsScreen(subject: subject, chapter: chapter),
                        )),
                      ),
                    );
                  },
                ),
        ),
      ),
    );
  }
}
