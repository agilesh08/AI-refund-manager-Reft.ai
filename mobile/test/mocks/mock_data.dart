/// Mock test data for unit and widget tests.
class MockData {
  static Map<String, dynamic> get customerVerificationJson => {
        'verification_id': 'sess_12345',
        'merchant': {
          'business_name': 'Acme Electronics',
          'support_email': 'support@acme.com',
        },
        'product': {
          'name': 'Noise Cancelling Headphones X',
          'sku': 'NCH-100',
          'brand': 'AcmeAudio',
          'category': 'Electronics',
        },
        'status': 'CREATED',
        'expires_at': '2026-10-01T12:00:00Z',
        'workflow': {
          'workflow_name': 'Electronics Standard Refund Flow',
          'total_steps': 4,
        },
      };

  static Map<String, dynamic> get workflowJson => {
        'verification_id': 'sess_12345',
        'workflow_name': 'Electronics Standard Refund Flow',
        'workflow_version': 1,
        'steps': [
          {
            'step_key': 'step_photo',
            'step_type': 'IMAGE',
            'title': 'Photo of the Defect',
            'description': 'Please take a clear photo of the damage.',
            'step_order': 1,
            'required': true,
            'config': {},
          },
          {
            'step_key': 'step_mcq',
            'step_type': 'MCQ',
            'title': 'Is the packaging intact?',
            'description': 'Select packaging state.',
            'step_order': 2,
            'required': true,
            'config': {
              'choices': ['Yes, completely intact', 'Partially torn', 'Missing'],
            },
          },
          {
            'step_key': 'step_text',
            'step_type': 'TEXT',
            'title': 'Issue Description',
            'description': 'Describe what happened when you turned it on.',
            'step_order': 3,
            'required': false,
            'config': {'placeholder': 'Details...'},
          },
        ],
      };

  static Map<String, dynamic> get fusionJson => {
        'id': 'fusion_999',
        'verification_session_id': 'sess_12345',
        'assessment_state': 'EVIDENCE_CONSISTENT',
        'overall_confidence': 0.94,
        'rules_evaluated': [
          {'rule_name': 'visual_damage_check', 'passed': true},
        ],
        'contradictions': [],
        'missing_evidence': [],
        'explanation': {
          'summary': 'Customer photo matches expected damage pattern with 94% confidence.',
        },
        'fusion_version': '1.0',
        'created_at': '2026-09-08T10:00:00Z',
      };

  static Map<String, dynamic> get dashboardListJson => {
        'items': [
          {
            'verification_id': 'sess_001',
            'order_id': 'ORD-9001',
            'product_name': 'Wireless Speaker',
            'refund_amount': 129.99,
            'status': 'IN_PROGRESS',
            'assessment_state': 'EVIDENCE_CONSISTENT',
            'confidence': 0.92,
            'customer_id': 'cust_01',
            'customer_email': 'alice@example.com',
            'latest_decision': null,
            'evidence_count': 2,
            'created_at': '2026-09-08T09:30:00Z',
          },
          {
            'verification_id': 'sess_002',
            'order_id': 'ORD-9002',
            'product_name': 'Gaming Monitor 27"',
            'refund_amount': 349.50,
            'status': 'COMPLETED',
            'assessment_state': 'INCONSISTENCY_DETECTED',
            'confidence': 0.88,
            'customer_id': 'cust_02',
            'customer_email': 'bob@example.com',
            'latest_decision': 'REFUND_REJECTED',
            'evidence_count': 3,
            'created_at': '2026-09-07T14:15:00Z',
          },
        ],
        'page': 1,
        'page_size': 20,
        'total': 2,
      };

  static Map<String, dynamic> get investigationDetailJson => {
        'verification': {
          'verification_id': 'sess_001',
          'status': 'IN_PROGRESS',
          'created_at': '2026-09-08T09:30:00Z',
          'latest_assessment_state': 'EVIDENCE_CONSISTENT',
        },
        'product': {
          'name': 'Wireless Speaker',
          'sku': 'SPK-200',
          'brand': 'Acme',
          'category': 'Audio',
        },
        'claim': {
          'order_id': 'ORD-9001',
          'customer_id': 'cust_01',
          'refund_reason': 'Item arrived with cracked casing',
          'refund_amount': 129.99,
          'claimed_item_condition': 'Damaged in transit',
        },
        'workflow': {
          'name': 'Audio Refund Flow',
          'version': 1,
        },
        'evidence_summary': {
          'total_items': 1,
          'images_count': 1,
        },
        'evidence_items': [
          {
            'id': 'ev_001',
            'verification_session_id': 'sess_001',
            'evidence_type': 'CUSTOMER_IMAGE',
            'original_filename': 'cracked_speaker.jpg',
            'workflow_step_key': 'step_photo',
            'created_at': '2026-09-08T09:35:00Z',
          },
        ],
        'visual_analysis_items': [
          {
            'evidence_id': 'ev_001',
            'key_visual_observations': ['Cracked plastic shell on upper left corner'],
          },
        ],
        'signal_items': [
          {
            'id': 'sig_001',
            'signal_type': 'DELIVERY',
            'source_type': 'CARRIER_API',
            'status': 'DELIVERED',
            'data': {'carrier': 'FedEx'},
          },
        ],
        'adaptive_requests': [],
        'fusion_result': {
          'id': 'fusion_001',
          'verification_session_id': 'sess_001',
          'assessment_state': 'EVIDENCE_CONSISTENT',
          'overall_confidence': 0.92,
          'contradictions': [],
          'explanation': {
            'summary': 'Visual evidence matches customer transit damage claim.',
          },
        },
        'timeline': [
          {
            'timestamp': '2026-09-08T09:30:00Z',
            'event_type': 'SESSION_CREATED',
            'title': 'Session Created',
            'description': 'Customer verification session initiated.',
            'source': 'SYSTEM',
          },
        ],
        'decisions': [],
      };
}
