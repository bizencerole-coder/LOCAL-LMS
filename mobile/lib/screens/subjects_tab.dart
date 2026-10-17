import 'package:flutter/material.dart';

import '../api/models.dart';
import '../state/app_state.dart';
import '../util/format.dart';
import '../widgets/brand.dart';
import '../widgets/layout.dart';
import '../widgets/states.dart';
import '../widgets/subject_card.dart';

/// The Subjects tab: every subject of the student's class.
class SubjectsTab extends StatelessWidget {
  const SubjectsTab({super.key, required this.loaderKey, required this.onReturn});

  final GlobalKey<LoaderState<List<SubjectItem>>> loaderKey;
  final VoidCallback onReturn;

  @override
  Widget build(BuildContext context) {
    final student = AppScope.of(context).student;
    return Loader<List<SubjectItem>>(
      key: loaderKey,
      load: () => AppScope.read(context).api.subjects(),
      builder: (context, subjects, reload) => RefreshIndicator(
        onRefresh: reload,
        child: LayoutBuilder(
          builder: (context, constraints) => ListView(
            padding: readablePadding(constraints.maxWidth, gutter: 20),
            children: [
              PageHeading(
                title: 'Subjects',
                subtitle: [student?.groupLabel ?? '', plural(subjects.length, 'subject')]
                    .where((part) => part.isNotEmpty)
                    .join(' · '),
              ),
              if (subjects.isEmpty)
                const MessageView(
                  icon: Icons.inbox_outlined,
                  title: 'No subjects yet',
                  message: 'Subjects for your class will appear here.',
                )
              else
                GridView.builder(
                  shrinkWrap: true,
                  physics: const NeverScrollableScrollPhysics(),
                  gridDelegate: SliverGridDelegateWithMaxCrossAxisExtent(
                    maxCrossAxisExtent: 320,
                    mainAxisExtent: SubjectCard.height(context),
                    crossAxisSpacing: 12,
                    mainAxisSpacing: 8,
                  ),
                  itemCount: subjects.length,
                  itemBuilder: (context, i) => SubjectCard(subject: subjects[i], onReturn: onReturn),
                ),
            ],
          ),
        ),
      ),
    );
  }
}
