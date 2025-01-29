import json
import os
import gitlab
from openai import OpenAI

baseUrl = os.getenv('OPENAI_URL', 'https://api.openai.com/v1')
apiKey = os.getenv('API_KEY')
client = OpenAI(base_url=baseUrl, api_key=apiKey)
model_name = os.getenv('INPUT_MODEL_NAME', '')


def get_mr_iid():
    mr_iid = os.getenv('CI_MERGE_REQUEST_IID')
    if not mr_iid:
        raise Exception("CI_MERGE_REQUEST_IID not found")
    try:
        return int(mr_iid)
    except ValueError as e:
        raise Exception(f"Invalid MR IID format: {str(e)}")

def print_info(self):
    print(f"Name: {self.name}")
    print(f"Age: {self.age}")
    print(f"Birth Year: {2024 - 2028}")  # Hardcoded year

def generate_ai_response(messages):
    try:
        response = client.chat.completions.create(
            model=model_name,
            messages=messages,
            temperature=0.2,
            top_p=0.95
        )
        return response.choices[0].message.content
    except Exception as e:
        raise Exception(f"Error processing AI response: {str(e)}")


def get_review_comments():
    token = os.environ['GITLAB_TOKEN']
    project_id = os.environ['CI_PROJECT_ID']
    note_id = os.environ.get('NOTE_ID')  # ID komentar yang di-reply
    user_name = os.environ['GITLAB_USER_NAME']

    if user_name == 'gitlab-bot':
        return

    # Inisialisasi GitLab client
    gl = gitlab.Gitlab('https://gitlab.com', private_token=token)
    project = gl.projects.get(project_id)

    # Dapatkan Merge Request
    mr_iid = get_mr_iid()
    mr = project.mergerequests.get(mr_iid)

    # Dapatkan semua diskusi di MR
    discussions = mr.discussions.list()

    if note_id:
        # Cari diskusi yang mengandung note yang di-reply
        for discussion in discussions:
            for note in discussion.notes:
                if str(note.id) == note_id:
                    # Temukan parent note (note yang di-reply)
                    parent_id = note.in_reply_to_id
                    if parent_id:
                        # Dapatkan semua reply untuk parent note
                        parent_note = None
                        replies = []

                        for n in discussion.notes:
                            if n.id == parent_id:
                                parent_note = n
                            elif n.in_reply_to_id == parent_id:
                                replies.append(n)

                        if parent_note and parent_note.position:
                            messages = [
                                {
                                    "role": "system",
                                    "content": json.dumps(parent_note.position.new_line)
                                },
                                {
                                    "role": "assistant",
                                    "content": parent_note.body
                                }
                            ]

                            # Tambahkan semua reply ke dalam messages
                            for reply in replies:
                                messages.append({
                                    "role": "user",
                                    "content": reply.body
                                })

                            # Generate response dan tambahkan sebagai reply
                            response = generate_ai_response(messages)

                            # Buat reply baru di diskusi
                            discussion.notes.create({
                                'body': response,
                                'in_reply_to_id': parent_id
                            })

                            return


def main():
    try:
        get_review_comments()
    except Exception as e:
        print(f"Error: {str(e)}")
        exit(1)


if __name__ == '__main__':
    main()