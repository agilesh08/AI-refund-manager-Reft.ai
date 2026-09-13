import 'package:flutter_test/flutter_test.dart';
import 'package:refund_verification_app/main.dart';
import 'package:shared_preferences/shared_preferences.dart';

void main() {
  setUp(() {
    SharedPreferences.setMockInitialValues({});
  });

  testWidgets('App initialization test', (WidgetTester tester) async {
    await tester.pumpWidget(const RefundVerificationApp());
    await tester.pumpAndSettle();

    // Verifies gateway screen renders initially
    expect(find.bySemanticsLabel('Reft.AI'), findsNWidgets(2));
    expect(find.text('Customer Verification'), findsOneWidget);
    expect(find.byTooltip('Merchant Login'), findsOneWidget);
  });
}
