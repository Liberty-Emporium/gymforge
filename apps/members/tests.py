"""
Unit tests for apps/members/tasks.py — single-tenant version.

All model access is mocked — no database needed.
No GymTenant loop or schema_context (removed in single-tenant refactor).
"""
import datetime
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase
from django.utils import timezone

import apps.members.tasks  # ensure module loaded so patch() can resolve


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_member(fcm_token='', days_inactive=20):
    user = MagicMock()
    user.first_name = 'Alice'
    user.email = 'alice@example.com'

    today = timezone.now().date()
    checkin = MagicMock()
    checkin.checked_in_at.date.return_value = today - datetime.timedelta(days=days_inactive)

    member = MagicMock()
    member.pk = 1
    member.user = user
    member.fcm_token = fcm_token
    member.join_date = today - datetime.timedelta(days=days_inactive)
    member.checkins.order_by.return_value.first.return_value = checkin
    return member


def _make_gym(trial_active=True, trial_days_ago=0, trial_emails_sent=None, gym_name='Test Gym'):
    today = timezone.now().date()
    gym = MagicMock()
    gym.gym_name = gym_name
    gym.owner_email = 'owner@testgym.com'
    gym.trial_active = trial_active
    gym.trial_start_date.date.return_value = today - datetime.timedelta(days=trial_days_ago)
    gym.trial_emails_sent = trial_emails_sent if trial_emails_sent is not None else []
    return gym


# ---------------------------------------------------------------------------
# send_reengagement_message
# ---------------------------------------------------------------------------

class SendReengagementMessageTest(SimpleTestCase):

    def test_sends_push_when_fcm_token_non_blank(self):
        member = _make_member(fcm_token='device_tok_abc')
        with patch('apps.members.tasks.FCMNotification') as MockFCM, \
             patch('apps.members.tasks.send_mail'):
            from apps.members.tasks import send_reengagement_message
            send_reengagement_message(member, 20)
        MockFCM.assert_called_once()
        kwargs = MockFCM.return_value.notify_single_device.call_args.kwargs
        assert kwargs['registration_id'] == 'device_tok_abc'
        assert kwargs['message_title'] == 'We miss you!'

    def test_skips_push_when_no_fcm_token(self):
        member = _make_member(fcm_token='')
        with patch('apps.members.tasks.FCMNotification') as MockFCM, \
             patch('apps.members.tasks.send_mail') as mock_mail:
            from apps.members.tasks import send_reengagement_message
            send_reengagement_message(member, 20)
        MockFCM.assert_not_called()
        mock_mail.assert_called_once()

    def test_email_contains_days_count_and_correct_subject(self):
        member = _make_member()
        with patch('apps.members.tasks.FCMNotification'), \
             patch('apps.members.tasks.send_mail') as mock_mail:
            from apps.members.tasks import send_reengagement_message
            send_reengagement_message(member, 42)
        kwargs = mock_mail.call_args.kwargs
        assert '42' in kwargs['message']
        assert kwargs['subject'] == 'We miss you at the gym!'
        assert kwargs['recipient_list'] == ['alice@example.com']

    def test_push_exception_does_not_prevent_email(self):
        member = _make_member(fcm_token='tok')
        with patch('apps.members.tasks.FCMNotification') as MockFCM, \
             patch('apps.members.tasks.send_mail') as mock_mail:
            MockFCM.return_value.notify_single_device.side_effect = Exception('FCM down')
            from apps.members.tasks import send_reengagement_message
            send_reengagement_message(member, 20)
        mock_mail.assert_called_once()


# ---------------------------------------------------------------------------
# check_member_retention — single-tenant (direct MemberProfile query)
# ---------------------------------------------------------------------------

class CheckMemberRetentionTest(SimpleTestCase):

    def _run_task(self, members):
        with patch('apps.members.tasks.MemberProfile') as MockMember, \
             patch('apps.members.tasks.MemberAIAlert') as MockAlert, \
             patch('apps.members.tasks.send_reengagement_message') as mock_send:
            (MockMember.objects.filter.return_value
             .select_related.return_value.distinct.return_value) = members
            from apps.members.tasks import check_member_retention
            check_member_retention()
        return mock_send, MockAlert

    def test_30_day_inactive_creates_alert_and_sends_message(self):
        member = _make_member(days_inactive=30)
        mock_send, MockAlert = self._run_task([member])
        MockAlert.objects.get_or_create.assert_called_once_with(
            member=member,
            alert_type='inactivity',
            is_resolved=False,
            defaults={'message': 'Member inactive for 30 days.'},
        )
        mock_send.assert_called_once_with(member, 30)

    def test_14_day_inactive_sends_message_but_no_alert(self):
        member = _make_member(days_inactive=14)
        mock_send, MockAlert = self._run_task([member])
        MockAlert.objects.get_or_create.assert_not_called()
        mock_send.assert_called_once_with(member, 14)

    def test_13_day_inactive_does_nothing(self):
        member = _make_member(days_inactive=13)
        mock_send, MockAlert = self._run_task([member])
        mock_send.assert_not_called()
        MockAlert.objects.get_or_create.assert_not_called()

    def test_continues_to_next_member_on_exception(self):
        member1 = _make_member(days_inactive=30)
        member1.checkins.order_by.side_effect = Exception('DB error')
        member2 = _make_member(days_inactive=30)
        member2.pk = 2
        mock_send, _ = self._run_task([member1, member2])
        mock_send.assert_called_once_with(member2, 30)


# ---------------------------------------------------------------------------
# send_birthday_messages — single-tenant
# ---------------------------------------------------------------------------

class SendBirthdayMessagesTest(SimpleTestCase):

    def _run_task(self, members, gym=None):
        if gym is None:
            gym = _make_gym()
        with patch('apps.gym.models.GymConfig.get', return_value=gym), \
             patch('apps.members.tasks.MemberProfile') as MockMember, \
             patch('apps.members.tasks.award_loyalty_points', return_value=100) as mock_award, \
             patch('apps.members.tasks.FCMNotification') as MockFCM, \
             patch('apps.members.tasks.send_mail') as mock_mail:
            (MockMember.objects.filter.return_value
             .select_related.return_value) = members
            from apps.members.tasks import send_birthday_messages
            send_birthday_messages()
        return mock_award, MockFCM, mock_mail

    def test_awards_birthday_loyalty_points(self):
        member = _make_member()
        mock_award, _, _ = self._run_task([member])
        mock_award.assert_called_once_with(member, 'birthday', description='Happy Birthday!')

    def test_sends_push_when_fcm_token_set(self):
        member = _make_member(fcm_token='tok_xyz')
        _, MockFCM, _ = self._run_task([member])
        MockFCM.return_value.notify_single_device.assert_called_once()
        kwargs = MockFCM.return_value.notify_single_device.call_args.kwargs
        assert kwargs['message_title'] == 'Happy Birthday! 🎂'
        assert '100' in kwargs['message_body']

    def test_skips_push_when_no_fcm_token(self):
        member = _make_member(fcm_token='')
        _, MockFCM, _ = self._run_task([member])
        MockFCM.return_value.notify_single_device.assert_not_called()

    def test_birthday_email_contains_gym_name_and_points(self):
        member = _make_member()
        _, _, mock_mail = self._run_task([member])
        mock_mail.assert_called_once()
        assert 'Test Gym' in mock_mail.call_args.kwargs['subject']
        assert '100' in mock_mail.call_args.kwargs['message']

    def test_push_exception_does_not_prevent_email(self):
        member = _make_member(fcm_token='tok')
        with patch('apps.gym.models.GymConfig.get', return_value=_make_gym()), \
             patch('apps.members.tasks.MemberProfile') as MockMember, \
             patch('apps.members.tasks.award_loyalty_points', return_value=50), \
             patch('apps.members.tasks.FCMNotification') as MockFCM, \
             patch('apps.members.tasks.send_mail') as mock_mail:
            MockMember.objects.filter.return_value.select_related.return_value = [member]
            MockFCM.return_value.notify_single_device.side_effect = Exception('FCM down')
            from apps.members.tasks import send_birthday_messages
            send_birthday_messages()
        mock_mail.assert_called_once()

    def test_continues_on_member_exception(self):
        member1 = _make_member()
        member2 = _make_member()
        member2.pk = 2
        with patch('apps.gym.models.GymConfig.get', return_value=_make_gym()), \
             patch('apps.members.tasks.MemberProfile') as MockMember, \
             patch('apps.members.tasks.award_loyalty_points') as mock_award, \
             patch('apps.members.tasks.FCMNotification'), \
             patch('apps.members.tasks.send_mail'):
            MockMember.objects.filter.return_value.select_related.return_value = [member1, member2]
            mock_award.side_effect = [Exception('db err'), 50]
            from apps.members.tasks import send_birthday_messages
            send_birthday_messages()
        assert mock_award.call_count == 2


# ---------------------------------------------------------------------------
# process_trial_statuses — single-tenant (one GymConfig row)
# ---------------------------------------------------------------------------

class ProcessTrialStatusesTest(SimpleTestCase):

    def _run_task(self, gym):
        with patch('apps.gym.models.GymConfig.get', return_value=gym), \
             patch('apps.members.tasks._send_trial_email') as mock_email:
            from apps.members.tasks import process_trial_statuses
            process_trial_statuses()
        return mock_email

    def test_no_gym_config_returns_early(self):
        """GymConfig.get() returns None → task exits immediately."""
        with patch('apps.gym.models.GymConfig.get', return_value=None), \
             patch('apps.members.tasks._send_trial_email') as mock_email:
            from apps.members.tasks import process_trial_statuses
            process_trial_statuses()
        mock_email.assert_not_called()

    def test_inactive_trial_returns_early(self):
        """trial_active=False → task exits immediately."""
        gym = _make_gym(trial_active=False)
        mock_email = self._run_task(gym)
        mock_email.assert_not_called()

    def test_day14_sets_trial_inactive_and_suspended(self):
        gym = _make_gym(trial_active=True, trial_days_ago=14)
        self._run_task(gym)
        assert gym.trial_active is False
        assert gym.subscription_status == 'suspended'
        gym.save.assert_called()

    def test_day14_sends_ended_email_if_not_already_sent(self):
        gym = _make_gym(trial_days_ago=14, trial_emails_sent=[])
        mock_email = self._run_task(gym)
        mock_email.assert_called_once_with(gym, 'day14_ended')

    def test_day14_does_not_resend_if_already_sent(self):
        gym = _make_gym(trial_days_ago=14, trial_emails_sent=[14])
        mock_email = self._run_task(gym)
        mock_email.assert_not_called()

    def test_nudge_day_sends_email_if_not_sent(self):
        gym = _make_gym(trial_days_ago=7, trial_emails_sent=[0, 3])
        mock_email = self._run_task(gym)
        mock_email.assert_called_once_with(gym, 'day7')

    def test_nudge_day_skips_if_already_sent(self):
        gym = _make_gym(trial_days_ago=7, trial_emails_sent=[0, 3, 7])
        mock_email = self._run_task(gym)
        mock_email.assert_not_called()

    def test_non_nudge_day_does_nothing(self):
        gym = _make_gym(trial_days_ago=5, trial_emails_sent=[0, 3])
        mock_email = self._run_task(gym)
        mock_email.assert_not_called()
        gym.save.assert_not_called()
