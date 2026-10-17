import 'package:flutter/material.dart';

import '../api/models.dart';
import '../widgets/content_tile.dart';
import 'image_viewer_screen.dart';
import 'notes_viewer_screen.dart';
import 'player_screen.dart';

/// Opens [content] in the screen for its type. Returns once the student is back (for
/// a video only after its final progress save), so the caller can reload its list.
Future<void> openContentItem(BuildContext context, ContentItem content, {String? subtitle}) async {
  switch (content.type) {
    case ContentType.video:
      await openLesson(context, contentId: content.id, title: content.title, subtitle: subtitle);
    case ContentType.pdf:
      await Navigator.of(context).push(MaterialPageRoute<void>(
        builder: (_) => NotesViewerScreen(contentId: content.id, title: content.title),
      ));
    case ContentType.image:
      await Navigator.of(context).push(MaterialPageRoute<void>(
        builder: (_) => ImageViewerScreen(contentId: content.id, title: content.title),
      ));
    case ContentType.unknown:
      ScaffoldMessenger.maybeOf(context)?.showSnackBar(const SnackBar(content: Text(unsupportedContentMessage)));
  }
}
