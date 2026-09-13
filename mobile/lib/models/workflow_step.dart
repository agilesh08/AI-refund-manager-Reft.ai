/// Dynamic frozen workflow step models.
class WorkflowStepItem {
  final String? id;
  final String? workflowId;
  final String stepKey;
  final String stepType;
  final String title;
  final String? description;
  final int stepOrder;
  final bool required;
  final Map<String, dynamic> config;

  WorkflowStepItem({
    this.id,
    this.workflowId,
    required this.stepKey,
    required this.stepType,
    required this.title,
    this.description,
    this.stepOrder = 1,
    this.required = true,
    this.config = const {},
  });

  factory WorkflowStepItem.fromJson(Map<String, dynamic> json) {
    return WorkflowStepItem(
      id: json['id'] as String?,
      workflowId: json['workflow_id'] as String?,
      stepKey: json['step_key'] as String? ?? 'step_${json['step_order'] ?? 1}',
      stepType: (json['step_type'] as String? ?? 'TEXT').toUpperCase(),
      title: json['title'] as String? ?? 'Step',
      description: json['description'] as String?,
      stepOrder: (json['step_order'] as num?)?.toInt() ?? 1,
      required: json['required'] as bool? ?? true,
      config: json['config'] is Map
          ? Map<String, dynamic>.from(json['config'] as Map)
          : (json['config_json'] is Map
              ? Map<String, dynamic>.from(json['config_json'] as Map)
              : const {}),
    );
  }

  // Config accessors
  List<WorkflowOption> get options {
    final list = config['options'] ?? config['choices'] ?? config['scenarios'];
    if (list is List) {
      return list.map((e) => WorkflowOption.fromDynamic(e)).toList();
    }
    return [];
  }

  List<String> get mcqChoices {
    final opts = options;
    if (opts.isNotEmpty) {
      return opts.map((o) => o.label).toList();
    }
    return [];
  }

  String? get placeholder => config['placeholder'] as String?;
  int? get minLength => (config['min_length'] as num?)?.toInt();
  int? get maxLength => (config['max_length'] as num?)?.toInt();
}

/// Scenario / option item for MCQ and workflow configuration.
class WorkflowOption {
  final String value;
  final String label;
  final String? description;
  final List<String> followUpQuestions;

  WorkflowOption({
    required this.value,
    required this.label,
    this.description,
    this.followUpQuestions = const [],
  });

  factory WorkflowOption.fromDynamic(dynamic raw) {
    if (raw is Map) {
      final map = Map<String, dynamic>.from(raw);
      final val = map['value']?.toString() ?? map['label']?.toString() ?? '';
      final lbl = map['label']?.toString() ?? (val.isNotEmpty ? val : 'Option');
      final desc = map['description']?.toString();
      final fqs = (map['follow_up_questions'] as List?)
              ?.map((q) => q.toString())
              .toList() ??
          const [];
      return WorkflowOption(
        value: val,
        label: lbl,
        description: desc,
        followUpQuestions: fqs,
      );
    }
    final s = raw.toString();
    return WorkflowOption(value: s, label: s);
  }

  Map<String, dynamic> toJson() => {
        'value': value,
        'label': label,
        if (description != null) 'description': description,
        if (followUpQuestions.isNotEmpty)
          'follow_up_questions': followUpQuestions,
      };
}

class CustomerWorkflowResponse {
  final String verificationId;
  final String workflowName;
  final int workflowVersion;
  final List<WorkflowStepItem> steps;

  CustomerWorkflowResponse({
    required this.verificationId,
    required this.workflowName,
    required this.workflowVersion,
    required this.steps,
  });

  factory CustomerWorkflowResponse.fromJson(Map<String, dynamic> json) {
    final rawSteps = json['steps'] as List<dynamic>? ?? [];
    final parsedSteps = rawSteps
        .map((s) => WorkflowStepItem.fromJson(Map<String, dynamic>.from(s as Map)))
        .toList()
      ..sort((a, b) => a.stepOrder.compareTo(b.stepOrder));

    return CustomerWorkflowResponse(
      verificationId: json['verification_id'] as String? ?? '',
      workflowName: json['workflow_name'] as String? ?? 'Verification Workflow',
      workflowVersion: (json['workflow_version'] as num?)?.toInt() ?? 1,
      steps: parsedSteps,
    );
  }
}
