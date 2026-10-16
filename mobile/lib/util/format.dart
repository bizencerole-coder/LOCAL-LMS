/// "4:05", "1:02:09".
String formatDuration(Duration d) {
  final negative = d.isNegative;
  final total = d.abs().inSeconds;
  final h = total ~/ 3600;
  final m = (total % 3600) ~/ 60;
  final s = total % 60;
  final body = h > 0
      ? '$h:${m.toString().padLeft(2, '0')}:${s.toString().padLeft(2, '0')}'
      : '$m:${s.toString().padLeft(2, '0')}';
  return negative ? '-$body' : body;
}

String formatSeconds(int? seconds) => seconds == null ? '--:--' : formatDuration(Duration(seconds: seconds));

/// "12 min", "1 h 5 min" for lesson lists.
String formatLength(int? seconds) {
  if (seconds == null || seconds <= 0) return '';
  if (seconds < 60) return '$seconds s';
  final minutes = (seconds / 60).round();
  if (minutes < 60) return '$minutes min';
  final h = minutes ~/ 60;
  final m = minutes % 60;
  return m == 0 ? '$h h' : '$h h $m min';
}

String plural(int count, String one, [String? many]) => '$count ${count == 1 ? one : (many ?? '${one}s')}';
