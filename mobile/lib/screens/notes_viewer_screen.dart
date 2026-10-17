import 'dart:async';
import 'dart:io';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:pdfx/pdfx.dart';

import '../api/api_client.dart';
import '../state/app_state.dart';
import '../widgets/states.dart';

const _cantOpen = 'These notes could not be opened. The file may be damaged; please tell your teacher.';

/// Shows notes (a PDF). The file is downloaded once (opening it is what the server
/// records) and drawn on the tablet by Android's PdfRenderer through pdfx, so paging,
/// zooming and rotating need no further network access.
class NotesViewerScreen extends StatefulWidget {
  const NotesViewerScreen({super.key, required this.contentId, required this.title});

  final String contentId;
  final String title;

  @override
  State<NotesViewerScreen> createState() => _NotesViewerScreenState();
}

class _NotesViewerScreenState extends State<NotesViewerScreen> {
  late final ApiClient _api;
  PdfDocument? _document;
  PdfControllerPinch? _controller;
  ApiException? _error;

  /// How much of the file has arrived (0.0–1.0), null while unknown.
  double? _progress;

  /// Incremented on every (re)load and on dispose, so a slow load that finishes
  /// after the student retried or left is discarded.
  int _generation = 0;

  @override
  void initState() {
    super.initState();
    _api = AppScope.read(context).api;
    _load();
  }

  @override
  void dispose() {
    _generation++;
    _release();
    super.dispose();
  }

  /// Also "Try again": opening the item again gets a fresh signed URL.
  Future<void> _load() async {
    final generation = ++_generation;
    if (_error != null || _controller != null) {
      _release();
      setState(() {
        _error = null;
        _progress = null;
      });
    }
    try {
      final file = await _api.fetchContentFile(widget.contentId, onProgress: (received, total) {
        if (!mounted || generation != _generation || total == null || total <= 0) return;
        final progress = received / total;
        // Repainting every couple of percent is plenty.
        if (progress - (_progress ?? 0) >= 0.02 || progress >= 1) setState(() => _progress = progress);
      });
      if (!mounted || generation != _generation) return;
      final document = await _openPdf(file.bytes);
      if (!mounted || generation != _generation) {
        _closeLater(document);
        return;
      }
      setState(() {
        _document = document;
        _controller = PdfControllerPinch(document: Future.value(document));
      });
    } on ApiException catch (e) {
      _fail(generation, e);
    } catch (_) {
      _fail(generation, const ApiException(ApiErrorKind.invalid, _cantOpen));
    }
  }

  void _fail(int generation, ApiException error) {
    if (mounted && generation == _generation) setState(() => _error = error);
  }

  /// Lets go of the open document. The controller is disposed after the next frame,
  /// once the view that uses it has left the tree.
  void _release() {
    final controller = _controller;
    final document = _document;
    _controller = null;
    _document = null;
    if (controller != null) WidgetsBinding.instance.addPostFrameCallback((_) => controller.dispose());
    if (document != null) _closeLater(document);
  }

  /// Closes [document] after any page render the view still has in flight is done
  /// (pdfx does not close documents shown with its pinch view).
  static void _closeLater(PdfDocument document) {
    Timer(const Duration(seconds: 2), () {
      if (!document.isClosed) document.close().ignore();
    });
  }

  /// Opens the downloaded bytes through a private temporary file that is deleted as soon
  /// as the renderer has it open (Android keeps an open file readable after its name is
  /// removed). pdfx's openData would leave its own copy in the app cache for every
  /// document opened.
  static Future<PdfDocument> _openPdf(Uint8List bytes) async {
    final File file;
    try {
      file = File('${Directory.systemTemp.path}${Platform.pathSeparator}'
          'notes-${DateTime.now().microsecondsSinceEpoch}.pdf');
      await file.writeAsBytes(bytes, flush: true);
    } on FileSystemException {
      return PdfDocument.openData(bytes);
    }
    try {
      return await PdfDocument.openFile(file.path);
    } finally {
      try {
        await file.delete();
      } on FileSystemException {
        // Already gone; the temporary folder is cleared by the system anyway.
      }
    }
  }

  Widget _body() {
    final error = _error;
    if (error != null) return ErrorView(error: error, onRetry: _load);
    final controller = _controller;
    final document = _document;
    if (controller == null || document == null) return LoadingView(message: 'Opening notes…', progress: _progress);

    return Stack(
      children: [
        Positioned.fill(
          child: PdfViewPinch(
            controller: controller,
            maxScale: 6,
            builders: PdfViewPinchBuilders<DefaultBuilderOptions>(
              options: const DefaultBuilderOptions(loaderSwitchDuration: Duration(milliseconds: 200)),
              documentLoaderBuilder: (_) => const LoadingView(message: 'Opening notes…'),
              pageLoaderBuilder: (_) => const Center(child: CircularProgressIndicator()),
              errorBuilder: (_, _) => ErrorView(
                error: const ApiException(ApiErrorKind.invalid, _cantOpen),
                onRetry: _load,
              ),
            ),
          ),
        ),
        Positioned(
          left: 16,
          right: 16,
          bottom: 16,
          child: SafeArea(
            top: false,
            child: Center(child: _PageIndicator(controller: controller, pagesCount: document.pagesCount)),
          ),
        ),
      ],
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text(widget.title)),
      backgroundColor: _controller != null ? Theme.of(context).colorScheme.surfaceContainerHighest : null,
      body: _body(),
    );
  }
}

/// "Page 2 of 5" over the bottom of the pages; it lets touches through to them.
class _PageIndicator extends StatelessWidget {
  const _PageIndicator({required this.controller, required this.pagesCount});

  final PdfControllerPinch controller;
  final int pagesCount;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final scheme = theme.colorScheme;
    return IgnorePointer(
      child: PdfPageNumber(
        controller: controller,
        builder: (context, state, page, count) => state != PdfLoadingState.success
            ? const SizedBox.shrink()
            : DecoratedBox(
                decoration: ShapeDecoration(
                  color: scheme.inverseSurface.withValues(alpha: 0.85),
                  shape: const StadiumBorder(),
                ),
                child: Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 6),
                  child: Text('Page $page of ${count ?? pagesCount}',
                      style: theme.textTheme.labelLarge?.copyWith(color: scheme.onInverseSurface)),
                ),
              ),
      ),
    );
  }
}
