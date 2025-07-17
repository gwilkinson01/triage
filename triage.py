import requests
from datetime import datetime, timedelta
import time
from newspaper import Article
from openai import OpenAI
import pytz
import json
import os

# OpenAI Client (loads from env var or pass your key here)
client = OpenAI(api_key="<apikeyhere>")

# Your Assistant ID (not model ID)
ASSISTANT_ID = "<idhere>"  # Replace with your actual Assistant ID

# Miniflux API setup
MINIFLUX_API_URL = "<urlhere>"
MINIFLUX_API_KEY = "<apikeyhere>"

# Path to the file where processed article IDs will be saved
PROCESSED_FILE = 'processed_articles.json'

# Slack Webhook URL
SLACK_WEBHOOK_URL = "https://hooks.slack.com/services/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"

# Function to send a message to Slack via Webhook
def send_to_slack(message):
    payload = {
        "text": f"{message}"
    }
    try:
        response = requests.post(SLACK_WEBHOOK_URL, json=payload)
        if response.status_code == 200:
            print("Message sent to Slack successfully!")
        else:
            print(f"Failed to send message to Slack, status code {response.status_code}")
    except Exception as e:
        print(f"Error sending message to Slack: {e}")

# Load the list of processed article IDs from a file
def load_processed_articles():
    if os.path.exists(PROCESSED_FILE):
        with open(PROCESSED_FILE, 'r') as f:
            try:
                processed_articles = json.load(f)
                print(f"✅ Loaded {len(processed_articles)} processed articles.")
                return processed_articles
            except json.JSONDecodeError:
                print("Error loading JSON data. Returning an empty list.")
                return []  # Return an empty list in case of error
    else:
        print(f"{PROCESSED_FILE} does not exist. Starting with an empty list.")
        return []

# Save the list of processed article IDs to the file
def save_processed_articles(processed_articles):
    try:
        # Ensure all article IDs are strings before saving
        processed_articles = [str(article_id) for article_id in processed_articles]
        with open(PROCESSED_FILE, 'w') as f:
            json.dump(processed_articles, f, indent=4)
        print(f"Saved {len(processed_articles)} processed articles to {PROCESSED_FILE}")
    except Exception as e:
        print(f"Error saving processed articles: {e}")

# Function to check and update processed articles
def process_article(entry, processed_articles):
    article_id = str(entry['id'])  # Ensure the 'id' is treated as a string
    if article_id in processed_articles:
        print(f"Skipping duplicate article: {entry['title']}")
        return True  # Return True to indicate this article was skipped

    # Proceed with processing the article (e.g., fetch and send to Assistant)
    print(f"Processing article: {entry['title']}")
    return False  # Return False to indicate this article was processed

# Get the timestamps for x hours ago and now
now = datetime.now(pytz.utc)
published_before = int(now.timestamp())
published_after = int((now - timedelta(hours=1)).timestamp())

# Fetch entries from Miniflux API
headers = {"X-Auth-Token": MINIFLUX_API_KEY}
params = {
    "published_after": published_after,
    "published_before": published_before
}

response = requests.get(MINIFLUX_API_URL, headers=headers, params=params)

if response.status_code == 200:
    entries = response.json().get("entries", [])
    print(f"Found {len(entries)} entries.\n")

    # Load previously processed articles
    processed_articles = load_processed_articles()

    # Debug: Print out processed articles list
    print(f"Current processed articles: {processed_articles}")

    for entry in entries:
        title = entry["title"]
        url = entry["url"]
        published_at = entry["published_at"]
        content = entry["content"]

        print(f"Title: {title}")
        print(f"Published: {published_at}")
        print(f"URL: {url}")

        try:
            # Extract full article content
            article = Article(url)
            article.download()
            article.parse()
            full_text = article.text

            # Check if the article is already processed
            if process_article(entry, processed_articles):
                continue  # Skip the rest of the loop if the article is a duplicate

            print("Sending article to Assistant...")

            # Create a thread
            thread = client.beta.threads.create()

            # Add user message to the thread
            client.beta.threads.messages.create(
                thread_id=thread.id,
                role="user",
                content=(
                    f"Title: {title}\n"
                    f"Published: {published_at}\n"
                    f"URL: {url}\n\n"
                    f"Content:\n{full_text}"
                )
            )

            # Run the assistant
            run = client.beta.threads.runs.create(
                thread_id=thread.id,
                assistant_id=ASSISTANT_ID
            )

            # Wait for completion
            while True:
                run_status = client.beta.threads.runs.retrieve(
                    thread_id=thread.id,
                    run_id=run.id
                )
                if run_status.status == "completed":
                    break
                elif run_status.status in ["failed", "cancelled", "expired"]:
                    raise Exception(f"Run failed with status: {run_status.status}")
                time.sleep(1)

            # Get the response
            messages = client.beta.threads.messages.list(thread_id=thread.id)
            last_msg = messages.data[0].content[0].text.value

            # Send the response to Slack via webhook
            send_to_slack(last_msg)

            # Article was successfully processed, so add it to the list of processed articles
            processed_articles.append(str(entry['id']))
            save_processed_articles(processed_articles)

        except Exception as e:
            print(f"Failed to process article: {e}\n")

        print("=" * 100)
else:
    print("Failed to fetch entries from Miniflux API.")