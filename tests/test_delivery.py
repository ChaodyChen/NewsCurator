"""
Tests for delivery module.

Coverage:
- verify_links_final()
- promote_reserve_story()
- format_line_message()
- send_via_line()
- send_via_email()
- deliver_news() — full pipeline
"""

import pytest
from unittest.mock import Mock, patch, MagicMock

from src.delivery import (
    DeliveryResult,
    verify_links_final,
    promote_reserve_story,
    format_line_message,
    send_via_line,
    send_via_email,
    deliver_news,
)


class TestVerifyLinksFinal:
    """Test verify_links_final() function."""

    @patch('src.delivery.requests.head')
    def test_verify_all_live(self, mock_head):
        """Test when all links are live."""
        mock_head.return_value = Mock(status_code=200)

        stories = [
            {'title': 'Article 1', 'url': 'https://example.com/1'},
            {'title': 'Article 2', 'url': 'https://example.com/2'},
        ]

        results = verify_links_final(stories)
        assert len(results) == 2
        assert all(is_live for _, is_live in results)

    @patch('src.delivery.requests.head')
    def test_verify_some_dead(self, mock_head):
        """Test when some links are dead."""
        # First call returns 200, second returns 404
        mock_head.side_effect = [
            Mock(status_code=200),
            Mock(status_code=404),
        ]

        stories = [
            {'title': 'Article 1', 'url': 'https://example.com/1'},
            {'title': 'Article 2', 'url': 'https://example.com/2'},
        ]

        results = verify_links_final(stories)
        assert len(results) == 2
        assert results[0][1] is True  # First is live
        assert results[1][1] is False  # Second is dead

    @patch('src.delivery.requests.head')
    def test_verify_timeout(self, mock_head):
        """Test URL verification timeout."""
        from requests.exceptions import Timeout
        mock_head.side_effect = Timeout("Request timed out")

        stories = [{'title': 'Article 1', 'url': 'https://example.com/1'}]

        results = verify_links_final(stories)
        assert len(results) == 1
        assert results[0][1] is False  # Marked as dead due to timeout


class TestPromoteReserveStory:
    """Test promote_reserve_story() function."""

    def test_promote_no_dead_links(self):
        """Test when no links are dead."""
        selected = [
            {'rank': '1', 'url': 'https://example.com/1', 'title': 'Article 1'},
            {'rank': '2', 'url': 'https://example.com/2', 'title': 'Article 2'},
            {'rank': '3', 'url': 'https://example.com/3', 'title': 'Article 3'},
            {'rank': '4', 'url': 'https://example.com/4', 'title': 'Article 4'},
            {'rank': '5', 'url': 'https://example.com/5', 'title': 'Article 5'},
            {'rank': '6', 'url': 'https://example.com/6', 'title': 'Article 6'},
            {'rank': '7', 'url': 'https://example.com/7', 'title': 'Article 7'},
        ]

        result = promote_reserve_story(selected, [], set())
        assert len(result) == 5
        assert [s['rank'] for s in result] == ['1', '2', '3', '4', '5']

    def test_promote_one_dead_link(self):
        """Test promoting one reserve when rank 3 is dead."""
        selected = [
            {'rank': '1', 'url': 'https://example.com/1', 'title': 'Article 1'},
            {'rank': '2', 'url': 'https://example.com/2', 'title': 'Article 2'},
            {'rank': '3', 'url': 'https://example.com/3', 'title': 'Article 3'},  # DEAD
            {'rank': '4', 'url': 'https://example.com/4', 'title': 'Article 4'},
            {'rank': '5', 'url': 'https://example.com/5', 'title': 'Article 5'},
            {'rank': '6', 'url': 'https://example.com/6', 'title': 'Article 6'},
            {'rank': '7', 'url': 'https://example.com/7', 'title': 'Article 7'},
        ]

        dead_urls = {'https://example.com/3'}
        result = promote_reserve_story(selected, [], dead_urls)

        assert len(result) == 5
        urls = [s['url'] for s in result]
        assert 'https://example.com/3' not in urls
        assert 'https://example.com/6' in urls  # Reserve promoted

    def test_promote_multiple_dead_links(self):
        """Test promoting multiple reserves."""
        selected = [
            {'rank': '1', 'url': 'https://example.com/1', 'title': 'Article 1'},
            {'rank': '2', 'url': 'https://example.com/2', 'title': 'Article 2'},  # DEAD
            {'rank': '3', 'url': 'https://example.com/3', 'title': 'Article 3'},
            {'rank': '4', 'url': 'https://example.com/4', 'title': 'Article 4'},  # DEAD
            {'rank': '5', 'url': 'https://example.com/5', 'title': 'Article 5'},
            {'rank': '6', 'url': 'https://example.com/6', 'title': 'Article 6'},
            {'rank': '7', 'url': 'https://example.com/7', 'title': 'Article 7'},
        ]

        dead_urls = {'https://example.com/2', 'https://example.com/4'}
        result = promote_reserve_story(selected, [], dead_urls)

        assert len(result) == 5
        urls = [s['url'] for s in result]
        assert 'https://example.com/2' not in urls
        assert 'https://example.com/4' not in urls
        assert 'https://example.com/6' in urls or 'https://example.com/7' in urls

    def test_promote_not_enough_reserves(self):
        """Test when dead links exceed available reserves."""
        selected = [
            {'rank': '1', 'url': 'https://example.com/1', 'title': 'Article 1'},  # DEAD
            {'rank': '2', 'url': 'https://example.com/2', 'title': 'Article 2'},  # DEAD
            {'rank': '3', 'url': 'https://example.com/3', 'title': 'Article 3'},  # DEAD
            {'rank': '4', 'url': 'https://example.com/4', 'title': 'Article 4'},
            {'rank': '5', 'url': 'https://example.com/5', 'title': 'Article 5'},
            {'rank': '6', 'url': 'https://example.com/6', 'title': 'Article 6'},  # Only 1 reserve
        ]

        dead_urls = {'https://example.com/1', 'https://example.com/2', 'https://example.com/3'}
        result = promote_reserve_story(selected, [], dead_urls)

        # Should still return 5 stories, keeping some dead ones
        assert len(result) == 5


class TestFormatLINEMessage:
    """Test format_line_message() function."""

    def test_format_message_structure(self):
        """Test message formatting in Traditional Chinese (EOSL style)."""
        stories = [
            {
                'title': 'Samsung 展示 HBM4E 實體晶片',
                'url': 'https://example.com/1',
                'source': 'TechPowerUp',
                'published_at': '2026-03-23T10:00:00Z',
                'snippet': 'Samsung 在 GTC 2026 展示了其次世代 HBM4E 解決方案，採用自家 2nm 製程生產 Logic Die'
            },
            {
                'title': 'Tower Semiconductor 與 Oriole Networks 合作',
                'url': 'https://example.com/2',
                'source': 'Semiconductor News',
                'published_at': '2026-03-16T14:30:00Z',
                'snippet': 'Tower Semiconductor 與 Oriole Networks 宣布策略合作開發 AI 光學交換平台'
            },
            {
                'title': 'Coherent 展示矽光子 CPO 技術',
                'url': 'https://example.com/3',
                'source': 'OFC 2026',
                'published_at': '2026-03-21T09:15:00Z',
                'snippet': 'Coherent 展示了基於 Silicon Photonics 的 6.4T 插槽式 CPO'
            },
            {
                'title': 'ASMPT 推出 AMICRA NANO 系統',
                'url': 'https://example.com/4',
                'source': 'Advanced Packaging News',
                'published_at': '2026-03-21T16:45:00Z',
                'snippet': 'ASMPT 宣佈新的 Advanced Packaging 解決方案'
            },
            {
                'title': 'Adeia 與 UMC 擴大合作',
                'url': 'https://example.com/5',
                'source': 'IP News',
                'published_at': '2026-03-11T11:20:00Z',
                'snippet': 'Adeia 與 UMC 延長 Hybrid Bonding 技術授權合作'
            },
        ]

        message = format_line_message(stories)
        assert 'EOSL Weekly Top 5 News' in message
        assert '1️⃣' in message
        assert '5️⃣' in message
        assert 'Samsung' in message
        assert 'HBM4E' in message
        # Should contain content snippet, not attribution
        assert 'Samsung 在 GTC 2026 展示' in message
        # Should NOT contain "根據...報導" attribution line
        assert '根據《TechPowerUp》' not in message
        # Should NOT contain footer with reference links note
        assert 'Reference links' not in message
        assert 'Google Drive' not in message

    def test_format_message_fewer_than_5(self):
        """Test formatting with <5 stories."""
        stories = [
            {
                'title': 'Semiconductor Research',
                'url': 'https://example.com/1',
                'source': 'SemiNews',
                'published_at': '2026-03-26T10:00:00Z',
                'snippet': 'New semiconductor research findings'
            },
            {
                'title': 'AI Chip Development',
                'url': 'https://example.com/2',
                'source': 'TechNews',
                'published_at': '2026-03-25T10:00:00Z',
                'snippet': 'Latest AI chip developments'
            },
            {
                'title': 'Memory Technology',
                'url': 'https://example.com/3',
                'source': 'Electronics',
                'published_at': '2026-03-24T10:00:00Z',
                'snippet': 'Advanced memory technologies'
            },
        ]

        message = format_line_message(stories)
        assert 'EOSL Weekly Top 5 News' in message
        assert '1️⃣' in message
        assert '3️⃣' in message
        assert '4️⃣' not in message
        assert 'Semiconductor Research' in message
        assert 'Memory Technology' in message

    def test_format_message_filters_itri(self):
        """Test that ITRI-related news is filtered out."""
        stories = [
            {
                'title': 'TSMC Advances',
                'url': 'https://example.com/1',
                'source': 'TechNews',
                'published_at': '2026-03-26T10:00:00Z'
            },
            {
                'title': '工研院 New Research Initiative',
                'url': 'https://example.com/2',
                'source': 'ITRINews',
                'published_at': '2026-03-25T10:00:00Z'
            },
            {
                'title': 'Samsung Breakthrough',
                'url': 'https://example.com/3',
                'source': 'ElectronicsNews',
                'published_at': '2026-03-24T10:00:00Z'
            },
            {
                'title': 'Industrial Technology Research Institute Update',
                'url': 'https://itri.org.tw/news',
                'source': 'ITRI',
                'published_at': '2026-03-23T10:00:00Z'
            },
        ]

        message = format_line_message(stories)
        # ITRI-related items should be filtered
        assert '工研院' not in message
        assert 'ITRI' not in message.split('由 News Curator')[0]  # Not in main content
        # Non-ITRI items should be present
        assert 'TSMC' in message
        assert 'Samsung' in message


class TestSendViaLINE:
    """Test send_via_line() function."""

    @patch('src.delivery.requests.post')
    def test_send_line_success(self, mock_post):
        """Test successful LINE delivery."""
        mock_post.return_value = Mock(status_code=200)

        result = send_via_line("Test message", "token123", "group456")
        assert result is True
        mock_post.assert_called_once()

    @patch('src.delivery.requests.post')
    def test_send_line_invalid_token(self, mock_post):
        """Test LINE delivery with invalid token."""
        mock_post.return_value = Mock(status_code=401, text="Unauthorized")

        result = send_via_line("Test message", "invalid_token", "group456")
        assert result is False

    @patch('src.delivery.requests.post')
    def test_send_line_rate_limited(self, mock_post):
        """Test LINE delivery when rate limited."""
        mock_post.return_value = Mock(status_code=429, text="Too Many Requests")

        result = send_via_line("Test message", "token123", "group456")
        assert result is False


class TestSendViaEmail:
    """Test send_via_email() function."""

    @patch('src.delivery.smtplib.SMTP')
    def test_send_email_success(self, mock_smtp_class):
        """Test successful email delivery."""
        mock_smtp = Mock()
        mock_smtp_class.return_value.__enter__.return_value = mock_smtp

        result = send_via_email(
            "Test message",
            "smtp.gmail.com",
            587,
            "user@example.com",
            "password",
            "recipient@example.com"
        )
        assert result is True
        mock_smtp.starttls.assert_called_once()
        mock_smtp.login.assert_called_once()
        mock_smtp.sendmail.assert_called_once()

    @patch('src.delivery.smtplib.SMTP')
    def test_send_email_auth_failure(self, mock_smtp_class):
        """Test email delivery with auth failure."""
        import smtplib
        mock_smtp = Mock()
        mock_smtp.login.side_effect = smtplib.SMTPAuthenticationError(401, "Authentication failed")
        mock_smtp_class.return_value.__enter__.return_value = mock_smtp

        result = send_via_email(
            "Test message",
            "smtp.gmail.com",
            587,
            "user@example.com",
            "wrong_password",
            "recipient@example.com"
        )
        assert result is False


class TestDeliverNews:
    """Test deliver_news() full pipeline."""

    @patch('src.delivery.send_via_line')
    @patch('src.delivery.format_line_message')
    @patch('src.delivery.promote_reserve_story')
    @patch('src.delivery.verify_links_final')
    @patch('src.curation_form.load_selections_csv')
    def test_deliver_success(
        self, mock_load_sel, mock_verify, mock_promote, mock_format, mock_send_line, tmp_path
    ):
        """Test successful end-to-end delivery."""
        from src.curation_form import CurationSelection

        # Create mock selections
        mock_selections = [
            CurationSelection('https://example.com/1', 'Article 1', '1'),
            CurationSelection('https://example.com/2', 'Article 2', '2'),
            CurationSelection('https://example.com/3', 'Article 3', '3'),
            CurationSelection('https://example.com/4', 'Article 4', '4'),
            CurationSelection('https://example.com/5', 'Article 5', '5'),
            CurationSelection('https://example.com/6', 'Article 6', '6'),
        ]
        mock_load_sel.return_value = mock_selections

        # Mock verification - all live
        mock_verify.return_value = [
            (s.to_dict(), True) for s in mock_selections
        ]

        # Mock promotion - no changes needed
        mock_promote.return_value = [s.to_dict() for s in mock_selections[:5]]

        # Mock message formatting
        mock_format.return_value = "Formatted message"

        # Mock LINE send - success
        mock_send_line.return_value = True

        result = deliver_news(
            "selections.csv",
            "candidates.csv",
            "token123",
            "group456"
        )

        assert result.success is True
        assert result.method == "line"
        mock_send_line.assert_called_once()

    @patch('src.delivery.send_via_email')
    @patch('src.delivery.send_via_line')
    @patch('src.delivery.format_line_message')
    @patch('src.delivery.promote_reserve_story')
    @patch('src.delivery.verify_links_final')
    @patch('src.curation_form.load_selections_csv')
    def test_deliver_line_fails_email_fallback(
        self, mock_load_sel, mock_verify, mock_promote, mock_format,
        mock_send_line, mock_send_email
    ):
        """Test LINE failure triggers email fallback."""
        from src.curation_form import CurationSelection

        # Setup mocks
        mock_selections = [
            CurationSelection('https://example.com/1', 'Article 1', '1'),
            CurationSelection('https://example.com/2', 'Article 2', '2'),
            CurationSelection('https://example.com/3', 'Article 3', '3'),
            CurationSelection('https://example.com/4', 'Article 4', '4'),
            CurationSelection('https://example.com/5', 'Article 5', '5'),
            CurationSelection('https://example.com/6', 'Article 6', '6'),
        ]
        mock_load_sel.return_value = mock_selections
        mock_verify.return_value = [(s.to_dict(), True) for s in mock_selections]
        mock_promote.return_value = [s.to_dict() for s in mock_selections[:5]]
        mock_format.return_value = "Formatted message"
        mock_send_line.return_value = False  # LINE fails
        mock_send_email.return_value = True  # Email succeeds

        result = deliver_news(
            "selections.csv",
            "candidates.csv",
            "token123",
            "group456",
            smtp_config={
                'smtp_server': 'smtp.gmail.com',
                'smtp_port': 587,
                'smtp_user': 'user@example.com',
                'smtp_password': 'password',
                'recipient': 'ops@example.com'
            }
        )

        assert result.success is False
        assert result.method == "email_fallback"
        mock_send_line.assert_called()
        mock_send_email.assert_called()

    @patch('src.curation_form.load_selections_csv')
    def test_deliver_missing_selections_file(self, mock_load_sel):
        """Test delivery with missing selections CSV."""
        mock_load_sel.return_value = []  # Empty selections

        result = deliver_news(
            "nonexistent.csv",
            "candidates.csv",
            "token123",
            "group456"
        )

        assert result.success is False
        assert "No selections found" in result.message
