"""
Deliver top 5 stories to LINE and handle fallback (email) delivery.

Monday 8:00 AM workflow:
1. Load selections from CSV
2. Get top 5 ranked stories
3. Verify links one more time (in case they died since Friday)
4. Replace any dead links with reserves (#6-7)
5. Format as LINE message
6. Send via LINE API
7. If LINE fails, send email alert to ops (user)
8. Log all delivery attempts
"""

import logging
import smtplib
import requests
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timezone
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
from requests.exceptions import RequestException, Timeout

logger = logging.getLogger(__name__)


@dataclass
class DeliveryResult:
    """Result of a delivery attempt."""
    success: bool
    method: str  # "line" or "email"
    timestamp: str
    message: str  # Status message or error details


def verify_links_final(stories: List[Dict], timeout_seconds: int = 5) -> List[Tuple[Dict, bool]]:
    """
    Final URL verification before delivery (in case links died since curation).

    Args:
        stories: List of stories (dicts with 'url', 'title')
        timeout_seconds: Timeout for HEAD request

    Returns:
        List of (story_dict, link_status) tuples
        link_status is True if accessible, False if dead/timeout
    """
    results = []

    for story in stories:
        url = story.get('url', '')
        if not url:
            logger.warning(f"Story missing URL: {story.get('title', 'Unknown')}")
            results.append((story, False))
            continue

        try:
            # Send HEAD request (faster than GET, just checks headers)
            response = requests.head(url, timeout=timeout_seconds, allow_redirects=True)

            # Return True for successful responses (2xx, 3xx status codes)
            # Return False for 404, 410, and other client/server errors
            is_live = 200 <= response.status_code < 400
            results.append((story, is_live))

            if not is_live:
                logger.warning(f"Dead link found: {url} (status {response.status_code})")

        except Timeout:
            logger.debug(f"URL timeout (>{timeout_seconds}s): {url}")
            results.append((story, False))
        except requests.exceptions.ConnectionError:
            logger.debug(f"Connection error verifying {url}")
            results.append((story, False))
        except requests.exceptions.RequestException as e:
            logger.debug(f"Request error verifying {url}: {e}")
            results.append((story, False))
        except Exception as e:
            logger.debug(f"Unexpected error verifying {url}: {e}")
            results.append((story, False))

    return results


def promote_reserve_story(
    selected_stories: List[Dict],
    all_candidates: List[Dict],
    dead_urls: set
) -> List[Dict]:
    """
    Replace dead links with reserve stories (3★).

    Args:
        selected_stories: User's rated stories (1-5 stars)
        all_candidates: All fetched candidates
        dead_urls: Set of URLs that are dead

    Returns:
        List of 5 stories with dead ones replaced by reserves

    Logic:
    - Keep stories 4★/5★ that have live links (top priority)
    - For each dead link in 4★/5★, promote next available from 3★
    - Return exactly 5 stories with live links
    """
    # Separate top (4-5 stars) and reserves (3 stars) by rank
    top_5 = sorted([s for s in selected_stories if s.get('rank') in ['4', '5']],
                   key=lambda s: -int(s['rank']))
    reserves = sorted([s for s in selected_stories if s.get('rank') == '3'],
                      key=lambda s: -int(s['rank']))

    # Start with all top 5 stories
    result = list(top_5)

    # Check for dead links in top 5 and replace with reserves
    for i, story in enumerate(result):
        if story.get('url') in dead_urls:
            logger.warning(f"Story {story.get('rank')} has dead link, looking for reserve")

            # Find first live reserve story
            for reserve in reserves:
                if reserve.get('url') not in dead_urls:
                    logger.info(f"Promoting reserve #{reserve.get('rank')}: {reserve.get('title')}")
                    result[i] = reserve
                    reserves.remove(reserve)
                    break
            else:
                # No live reserves found - keep the dead link
                logger.warning(f"No live reserves available, keeping dead link #{story.get('rank')}")

    # Return exactly 5 stories
    return result[:5]


def format_line_message(top_stories: List[Dict]) -> str:
    """
    Format top 5 stories as LINE message (Traditional Chinese, EOSL style).

    Format:
    ```
    Weekly EOSL五大重要技術摘要 YYYY/MM/DD - YYYY/MM/DD

    1️⃣ [Title in Chinese]
    [詳細段落說明，包含來源和日期]

    2️⃣ [Next title]
    [詳細說明...]

    ---
    Reference links stored in Google Drive
    ```

    Args:
        top_stories: List of stories (dicts with title, url, source, published_at, snippet)

    Returns:
        Formatted LINE message string in Traditional Chinese
    """
    if not top_stories:
        return "無可推送的新聞"

    # Filter out ITRI-related news
    filtered_stories = [
        s for s in top_stories
        if not _is_itri_related(s.get('title', '')) and not _is_itri_related(s.get('url', ''))
    ]

    if not filtered_stories:
        return "本週無符合條件的新聞"

    # Get date range (from first story to today)
    now = datetime.now(timezone.utc)
    date_end = now.strftime('%Y/%m/%d')

    # Try to get start date from oldest story (last in list)
    try:
        oldest = filtered_stories[-1].get('published_at', '')
        if oldest:
            oldest_date = datetime.fromisoformat(oldest.replace('Z', '+00:00'))
            # Go back 7 days as typical week range
            oldest_date = oldest_date - __import__('datetime').timedelta(days=7)
            date_start = oldest_date.strftime('%Y/%m/%d')
        else:
            # Default to 7 days ago
            start = now - __import__('datetime').timedelta(days=7)
            date_start = start.strftime('%Y/%m/%d')
    except (ValueError, AttributeError):
        start = now - __import__('datetime').timedelta(days=7)
        date_start = start.strftime('%Y/%m/%d')

    # Build message
    lines = [
        f"EOSL Weekly Top 5 News {date_start} - {date_end}",
        ""
    ]

    emoji_list = ['1️⃣', '2️⃣', '3️⃣', '4️⃣', '5️⃣']

    for idx, story in enumerate(filtered_stories[:5], 1):
        title = story.get('title', 'Untitled')
        url = story.get('url', '')
        snippet = story.get('snippet', '')

        emoji = emoji_list[idx - 1] if idx <= len(emoji_list) else f"{idx}."
        lines.append(f"{emoji} {title}")
        if snippet:
            lines.append(snippet)
        lines.append(url)
        lines.append("")

    lines.append("---")
    lines.append("EOSL Semiconductor Curation")

    return "\n".join(lines)


def _is_itri_related(text: str) -> bool:
    """
    Check if text is related to ITRI (工研院).

    Args:
        text: Text to check (title, URL, etc.)

    Returns:
        True if ITRI-related, False otherwise
    """
    itri_keywords = [
        '工研院',
        'ITRI',
        'Industrial Technology Research Institute',
        '工業技術研究院',
    ]
    text_lower = text.lower()
    return any(keyword.lower() in text_lower for keyword in itri_keywords)


def send_via_line(message: str, access_token: str, group_id: str) -> bool:
    """
    Send message to LINE group.

    Args:
        message: Formatted message text
        access_token: LINE Channel Access Token
        group_id: LINE group ID

    Returns:
        True if sent successfully, False otherwise

    Raises:
        Exception: On network/API errors (should be caught and logged)
    """
    if not access_token or not group_id:
        logger.error("Missing LINE credentials (token or group_id)")
        return False

    try:
        # LINE Messaging API endpoint
        url = "https://api.line.me/v2/bot/message/push"

        # Request headers
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {access_token}"
        }

        # Request body
        payload = {
            "to": group_id,
            "messages": [
                {
                    "type": "text",
                    "text": message
                }
            ]
        }

        # Send request
        response = requests.post(url, json=payload, headers=headers, timeout=10)

        if response.status_code == 200:
            logger.info(f"Successfully sent message to LINE group {group_id}")
            return True
        else:
            logger.error(f"LINE API error: {response.status_code} - {response.text}")
            return False

    except Timeout:
        logger.error("LINE API request timeout")
        return False
    except requests.exceptions.RequestException as e:
        logger.error(f"LINE API request failed: {e}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error sending via LINE: {e}")
        return False


def send_via_email(
    message: str,
    smtp_server: str,
    smtp_port: int,
    smtp_user: str,
    smtp_password: str,
    recipient: str,
    subject: str = "Semiconductor News Curation Alert"
) -> bool:
    """
    Send message via email (fallback if LINE fails).

    Args:
        message: Message to send
        smtp_server: SMTP server address
        smtp_port: SMTP port
        smtp_user: SMTP user (sender)
        smtp_password: SMTP password
        recipient: Email recipient (user/ops)
        subject: Email subject

    Returns:
        True if sent successfully, False otherwise
    """
    if not all([smtp_server, smtp_user, smtp_password, recipient]):
        logger.error("Missing email configuration")
        return False

    try:
        # Create message
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = smtp_user
        msg['To'] = recipient

        # Create plain text and HTML versions
        text = message
        html = f"<html><body><pre>{message}</pre></body></html>"

        msg.attach(MIMEText(text, 'plain'))
        msg.attach(MIMEText(html, 'html'))

        # Connect to SMTP server and send
        with smtplib.SMTP(smtp_server, smtp_port, timeout=10) as server:
            server.starttls()  # Upgrade connection to TLS
            server.login(smtp_user, smtp_password)
            server.sendmail(smtp_user, recipient, msg.as_string())

        logger.info(f"Successfully sent email to {recipient}")
        return True

    except smtplib.SMTPAuthenticationError:
        logger.error("SMTP authentication failed - check credentials")
        return False
    except smtplib.SMTPException as e:
        logger.error(f"SMTP error: {e}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error sending email: {e}")
        return False


def deliver_news(
    selections_filepath: str,
    all_candidates_filepath: str,
    line_access_token: str,
    line_group_id: str,
    smtp_config: Optional[Dict] = None,
    max_retries: int = 3,
) -> DeliveryResult:
    """
    Full Monday 8am delivery pipeline.

    Args:
        selections_filepath: Path to selections CSV
        all_candidates_filepath: Path to candidates CSV
        line_access_token: LINE API token
        line_group_id: LINE group ID
        smtp_config: Dict with smtp_server, smtp_port, smtp_user, smtp_password, recipient
        max_retries: Number of retries for LINE delivery

    Returns:
        DeliveryResult object with success status

    Logic:
    1. Load selections
    2. Get top 5 ranked stories
    3. Load all candidates (for reserve stories)
    4. Verify links final time
    5. Promote reserves if links are dead
    6. Format LINE message
    7. Attempt LINE delivery (with retries)
    8. If LINE fails, send email alert (if smtp_config provided)
    9. Return result
    """
    try:
        from src.curation_form import load_selections_csv, get_top_n_ranked

        logger.info("Starting Monday delivery pipeline...")

        # Step 1: Load selections
        logger.info("Step 1: Loading selections from CSV...")
        try:
            selections = load_selections_csv(selections_filepath)
            if not selections:
                return DeliveryResult(
                    success=False,
                    method="error",
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    message="No selections found - nothing to deliver"
                )
            logger.info(f"Loaded {len(selections)} selections")
        except Exception as e:
            logger.error(f"Failed to load selections: {e}")
            return DeliveryResult(
                success=False,
                method="error",
                timestamp=datetime.now(timezone.utc).isoformat(),
                message=f"Failed to load selections: {e}"
            )

        # Step 2: Get top 5 and all ranked stories (for reserves)
        logger.info("Step 2: Extracting top stories...")
        # Get top 5 main stories (4★/5★) + reserves (3★)
        top_5 = get_top_n_ranked(selections, n=5)
        top_5_for_verify = get_top_n_ranked(selections, n=5)

        if len(top_5_for_verify) < 5:
            logger.warning(f"Only {len(top_5_for_verify)} stories available, need at least 5")

        # Step 3: Verify links final time
        logger.info("Step 3: Verifying links (final check)...")
        verified_stories = verify_links_final(top_5, timeout_seconds=5)

        dead_urls = set(story['url'] for story, is_live in verified_stories if not is_live)
        logger.info(f"Found {len(dead_urls)} dead links")

        # Step 4: Promote reserves if needed
        logger.info("Step 4: Checking for reserve promotion...")
        if dead_urls:
            # Convert to list with rank field for promote_reserve_story
            selection_list = []
            for sel in selections:
                selection_list.append({
                    'url': sel.url,
                    'title': sel.title,
                    'rank': sel.rank
                })

            final_stories = promote_reserve_story(selection_list, [], dead_urls)
        else:
            # No dead links - just use top 5
            final_stories = top_5_for_verify

        if not final_stories:
            return DeliveryResult(
                success=False,
                method="error",
                timestamp=datetime.now(timezone.utc).isoformat(),
                message="No stories available after reserve promotion"
            )

        logger.info(f"Final delivery list: {len(final_stories)} stories")

        # Step 5: Format message
        logger.info("Step 5: Formatting LINE message...")
        line_message = format_line_message(final_stories)

        # Step 6: Attempt LINE delivery with retries
        logger.info(f"Step 6: Sending via LINE (max {max_retries} retries)...")
        line_success = False
        for attempt in range(max_retries):
            if send_via_line(line_message, line_access_token, line_group_id):
                line_success = True
                logger.info(f"LINE delivery succeeded on attempt {attempt + 1}")
                break
            else:
                logger.warning(f"LINE delivery attempt {attempt + 1} failed")
                if attempt < max_retries - 1:
                    logger.info("Retrying...")

        if line_success:
            return DeliveryResult(
                success=True,
                method="line",
                timestamp=datetime.now(timezone.utc).isoformat(),
                message=f"Successfully delivered to LINE group {line_group_id}"
            )

        # Step 7: If LINE failed, send email alert
        logger.info("Step 7: LINE failed, attempting email fallback...")
        if smtp_config:
            email_message = (
                f"LINE delivery FAILED after {max_retries} attempts.\n\n"
                f"Would have sent:\n{line_message}\n\n"
                f"Please check LINE API credentials and retry manually."
            )
            email_success = send_via_email(
                email_message,
                smtp_config.get('smtp_server', ''),
                smtp_config.get('smtp_port', 587),
                smtp_config.get('smtp_user', ''),
                smtp_config.get('smtp_password', ''),
                smtp_config.get('recipient', '')
            )

            if email_success:
                return DeliveryResult(
                    success=False,
                    method="email_fallback",
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    message=f"LINE failed, alert sent to {smtp_config.get('recipient')}"
                )
            else:
                logger.error("Both LINE and email delivery failed")
        else:
            logger.warning("No SMTP config provided for email fallback")

        return DeliveryResult(
            success=False,
            method="error",
            timestamp=datetime.now(timezone.utc).isoformat(),
            message="LINE delivery failed and no email fallback configured"
        )

    except Exception as e:
        logger.error(f"Unexpected error in delivery pipeline: {e}")
        return DeliveryResult(
            success=False,
            method="error",
            timestamp=datetime.now(timezone.utc).isoformat(),
            message=f"Delivery pipeline error: {e}"
        )
