from strands.session.file_session_manager import FileSessionManager


def get_memory_session_manager(session_id: str = "default_session_id"):
    session_manager = FileSessionManager(session_id=session_id, session_dir="./memory/sessions")
    return session_manager