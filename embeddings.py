"""
ЭМБЕДДИНГИ
"""
import numpy as np
from config import EMBEDDING_MODEL

_model = None

def _load_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        print("[EMBEDDINGS] Загружаю модель {}...".format(EMBEDDING_MODEL))
        _model = SentenceTransformer(EMBEDDING_MODEL)
        print("[EMBEDDINGS] Модель загружена")
    return _model


def get_vector(text):
    model = _load_model()
    vec = model.encode(text, convert_to_numpy=True)
    return vec.astype('float32')


def get_vectors_batch(texts):
    model = _load_model()
    vecs = model.encode(texts, convert_to_numpy=True)
    return [v.astype('float32') for v in vecs]
