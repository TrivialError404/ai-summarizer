
import json


def summarize_emails():
    from email_fetcher import get_emails_default
    from html_to_markdown import html_to_markdown_for_llm, remove_reply
    from llm_ollama import query_ollama
    from email_fetcher import save_emails

    from_file = False
    
    # Get emails
    file = "temp/emails.json"
    if from_file:
        with open(file, "r", encoding="utf-8") as f:
            emails = json.load(f)
    else:
        emails = get_emails_default()
        save_emails(emails, file)

    # Process each email
    for email in emails:
        print(email["uid"], "|", email["Subject"])

        # Extrace email content
        if email["text/html"]:
            content = email["text/html"]
            # HTML to Markdown
            content = html_to_markdown_for_llm(content)
        else:
            content = email["text/plain"]
        content = remove_reply(content)
        email["content"] = content

        # Summarize email content with a llm from ollama
        llm_prompt = """Task: Summarize.

Rules:
- Output exactly 2 sentences in German.
- Do NOT write a reply.
- Do NOT address the sender.
- Only summarize the content.

Email:"""
        email["promt"] = llm_prompt + " ... [content]"
        llm_prompt = llm_prompt + "\n\n" + content
        llm_response = query_ollama(llm_prompt, collect_metrics=True)
        print(llm_response["response"], "\n")
        email["llm_response"] = llm_response

        # Save to file
        file = "temp/emails_llm.json"
        save_emails(emails, file)


if __name__ == "__main__":
    summarize_emails()