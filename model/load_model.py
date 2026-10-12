
# 일단 테스트용으로 ChatGPT 모델 사용
from strands.models.openai import OpenAIModel

def load_model(model_id):
    
    model = OpenAIModel(
        client_args={
            "api_key": "lm-studio",
            "base_url": "http://127.0.0.1:1234/v1",
        },
        model_id=model_id,
    )

    return model