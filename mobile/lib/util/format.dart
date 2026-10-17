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

/// "12 min", "1 h 5 min" for video lengths in lists.
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

/// "850 KB", "2.3 MB" for file sizes (1 KB = 1024 bytes, as Windows shows them to teachers).
String formatBytes(int? bytes) {
  if (bytes == null || bytes <= 0) return '';
  if (bytes < 1024) return '$bytes B';
  const units = ['KB', 'MB', 'GB'];
  var value = bytes / 1024;
  var unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit++;
  }
  var text = unit == 0 || value >= 100 ? value.round().toString() : value.toStringAsFixed(1);
  if (text.endsWith('.0')) text = text.substring(0, text.length - 2);
  return '$text ${units[unit]}';
}

/// "6 videos · 2 notes · 1 image", leaving out types there are none of. Items of
/// types this version does not know (counted in [total] only) are "other items".
String contentCounts({int videos = 0, int notes = 0, int images = 0, int total = 0}) {
  final known = videos + notes + images;
  return [
    if (videos > 0) plural(videos, 'video'),
    if (notes > 0) plural(notes, 'note'),
    if (images > 0) plural(images, 'image'),
    if (total > known) plural(total - known, known == 0 ? 'item' : 'other item'),
  ].join(' · ');
}

const _months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const _monthsLong = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December',
];
const _weekdays = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];

/// "Good morning" before noon, "Good afternoon" until 5 pm, then "Good evening".
String greetingFor(DateTime time) => time.hour < 12
    ? 'Good morning'
    : time.hour < 17
        ? 'Good afternoon'
        : 'Good evening';

/// "Anu" for "Anu K".
String firstNameOf(String fullName) {
  final words = fullName.trim().split(RegExp(r'\s+'));
  return words.first;
}

/// "Friday, 17 October".
String formatDayHeading(DateTime time) =>
    '${_weekdays[time.weekday - 1]}, ${time.day} ${_monthsLong[time.month - 1]}';

/// "17 Oct 2026", in local time.
String formatDate(DateTime time) {
  final t = time.toLocal();
  return '${t.day} ${_months[t.month - 1]} ${t.year}';
}

/// "17 Oct 2026, 09:05", in local time.
String formatDateTime(DateTime time) {
  final t = time.toLocal();
  return '${formatDate(t)}, ${t.hour.toString().padLeft(2, '0')}:${t.minute.toString().padLeft(2, '0')}';
}

/// "Just now", "12 min ago", "3 h ago", "Yesterday", "4 days ago", then the date.
String formatRelativeTime(DateTime time, {DateTime? now}) {
  final current = (now ?? DateTime.now()).toLocal();
  final local = time.toLocal();
  final diff = current.difference(local);
  if (diff.inMinutes < 1) return 'Just now';
  if (diff.inMinutes < 60) return '${diff.inMinutes} min ago';
  final today = DateTime(current.year, current.month, current.day);
  final day = DateTime(local.year, local.month, local.day);
  final days = today.difference(day).inDays;
  if (days == 0) return '${diff.inHours} h ago';
  if (days == 1) return 'Yesterday';
  if (days < 7) return '$days days ago';
  return formatDate(local);
}
