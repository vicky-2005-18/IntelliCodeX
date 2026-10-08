"""
BM25 Lexical Indexer for Software Repositories (Milestone 3)
Provides inverted indexing with code-aware tokenization (camelCase & snake_case splitting)
and BM25 Okapi probabilistic scoring for precise exact symbol and variable lookup.
"""
import math
import re
from collections import defaultdict, Counter
from typing import List, Dict, Tuple, Optional, Set
from core.chunker import CodeChunk


# Regex to split on punctuation and whitespace while preserving code identifiers
WORD_SPLIT_REGEX = re.compile(r"[^\w]+", re.UNICODE)
# Regex to match camelCase / PascalCase word boundaries: e.g. "getUserById" -> "get", "User", "By", "Id"
CAMEL_SPLIT_REGEX = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")


def tokenize_code(text: str) -> List[str]:
    """
    Code-aware tokenizer:
    1. Splits text into raw identifier and literal tokens.
    2. Further deconstructs camelCase, PascalCase, and snake_case compounds into sub-tokens.
    3. Retains both compound tokens (e.g. 'SessionManager', 'get_user_by_username')
       and individual word fragments (e.g. 'session', 'manager', 'get', 'user').
    4. Normalizes all tokens to lowercase for case-insensitive matching.
    """
    if not text:
        return []

    raw_tokens = WORD_SPLIT_REGEX.split(text)
    tokens: List[str] = []

    for token in raw_tokens:
        token = token.strip()
        if not token:
            continue

        lower_token = token.lower()
        tokens.append(lower_token)

        # Split on underscores (snake_case)
        if "_" in token:
            sub_parts = token.split("_")
            for sp in sub_parts:
                sp_clean = sp.strip().lower()
                if sp_clean and sp_clean != lower_token:
                    tokens.append(sp_clean)

        # Split on CamelCase / PascalCase
        camel_parts = CAMEL_SPLIT_REGEX.split(token)
        if len(camel_parts) > 1:
            for cp in camel_parts:
                cp_clean = cp.strip().lower()
                if cp_clean and cp_clean != lower_token:
                    tokens.append(cp_clean)

    return tokens


# Small, documented stopword list for BM25 query term normalization
STOPWORDS: Set[str] = {
    "a", "about", "above", "after", "again", "against", "all", "am", "an", "and",
    "any", "are", "aren't", "as", "at", "be", "because", "been", "before", "being",
    "below", "between", "both", "but", "by", "can", "can't", "cannot", "could",
    "couldn't", "did", "didn't", "do", "does", "doesn't", "doing", "don't", "down",
    "during", "each", "few", "for", "from", "further", "had", "hadn't", "has",
    "hasn't", "have", "haven't", "having", "he", "her", "here", "hers", "herself",
    "him", "himself", "his", "how", "i", "if", "in", "into", "is", "isn't", "it",
    "it's", "its", "itself", "let's", "me", "more", "most", "mustn't", "my",
    "myself", "no", "nor", "not", "of", "off", "on", "once", "only", "or", "other",
    "ought", "our", "ours", "ourselves", "out", "over", "own", "same", "shan't",
    "she", "should", "shouldn't", "so", "some", "such", "than", "that", "that's",
    "the", "their", "theirs", "them", "themselves", "then", "there", "there's",
    "these", "they", "they'd", "they'll", "they're", "they've", "this", "those",
    "through", "to", "too", "under", "until", "up", "very", "was", "wasn't", "we",
    "we'd", "we'll", "we're", "we've", "were", "weren't", "what", "what's", "when",
    "where", "which", "while", "who", "whom", "why", "with", "won't", "would",
    "wouldn't", "you", "you'd", "you'll", "you're", "you've", "your", "yours",
    "yourself", "yourselves"
}


def tokenize_query(query: str, remove_stopwords: bool = True) -> List[str]:
    """
    Tokenizes a search query for BM25:
    1. Strips @file / @path mentions from the query text before tokenizing.
    2. Deconstructs identifiers into sub-tokens via code-aware tokenization.
    3. Removes common English stopwords (how, does, the, is, what, ...).
    4. Deduplicates terms while preserving original occurrence order.
    """
    if not query:
        return []

    # Remove @file mentions completely (both path, filename, and extension)
    cleaned = re.sub(r'@[\w\-.\/]+', ' ', query)
    raw_tokens = tokenize_code(cleaned)

    seen: Set[str] = set()
    deduped_tokens: List[str] = []

    for tok in raw_tokens:
        tok_lower = tok.lower()
        if remove_stopwords and tok_lower in STOPWORDS:
            continue
        if tok_lower not in seen:
            seen.add(tok_lower)
            deduped_tokens.append(tok_lower)

    return deduped_tokens


class BM25Index:
    """
    Inverted index implementation using the BM25 Okapi probabilistic ranking model.
    Optimized for source code tokens, symbols, docstrings, and function names.
    """
    def __init__(
        self,
        chunks: Optional[List[CodeChunk]] = None,
        k1: float = 1.5,
        b: float = 0.75,
    ):
        self.k1 = k1
        self.b = b
        self.chunks: List[CodeChunk] = []
        self.doc_lengths: List[int] = []
        self.avgdl: float = 0.0
        self.doc_freqs: Dict[str, int] = defaultdict(int)
        self.inverted_index: Dict[str, Dict[int, int]] = defaultdict(dict)  # term -> {doc_idx: freq}
        self.total_docs: int = 0

        if chunks:
            self.build_index(chunks)

    def build_index(self, chunks: List[CodeChunk]):
        """Builds the BM25 inverted index from a list of code chunks."""
        self.chunks = list(chunks)
        self.total_docs = len(self.chunks)
        self.doc_lengths = []
        self.doc_freqs.clear()
        self.inverted_index.clear()

        total_length = 0

        for idx, chunk in enumerate(self.chunks):
            # Include chunk symbol name, docstring, and implementation code.
            # File path is excluded from BM25 text to prevent score inflation and ties across chunks.
            text_to_index = f"{chunk.name} {chunk.docstring or ''} {chunk.code}"
            tokens = tokenize_code(text_to_index)
            doc_len = len(tokens)
            self.doc_lengths.append(doc_len)
            total_length += doc_len

            term_counts = Counter(tokens)
            for term, count in term_counts.items():
                self.doc_freqs[term] += 1
                self.inverted_index[term][idx] = count

        self.avgdl = (total_length / self.total_docs) if self.total_docs > 0 else 1.0

    def idf(self, term: str) -> float:
        """
        Computes Okapi IDF with smoothing to ensure non-negative values:
        IDF(q) = ln(1 + (N - n(q) + 0.5) / (n(q) + 0.5))
        """
        n = self.doc_freqs.get(term, 0)
        return math.log(1.0 + (self.total_docs - n + 0.5) / (n + 0.5))

    def search(self, query: str, top_k: int = 5) -> List[Tuple[CodeChunk, float]]:
        """
        Searches the inverted index with BM25 Okapi scoring.
        Returns top-K matching CodeChunks and their BM25 scores.
        """
        if not query or self.total_docs == 0:
            return []

        query_tokens = tokenize_query(query, remove_stopwords=True)
        if not query_tokens:
            return []

        scores: Dict[int, float] = defaultdict(float)

        for term in query_tokens:
            if term not in self.inverted_index:
                continue

            term_idf = self.idf(term)
            if term_idf <= 0:
                continue

            postings = self.inverted_index[term]
            for doc_idx, freq in postings.items():
                doc_len = self.doc_lengths[doc_idx]
                # BM25 TF normalization
                numerator = freq * (self.k1 + 1.0)
                denominator = freq + self.k1 * (1.0 - self.b + self.b * (doc_len / self.avgdl))
                scores[doc_idx] += term_idf * (numerator / denominator)

        if not scores:
            return []

        ranked_docs = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:top_k]
        return [(self.chunks[doc_idx], round(score, 4)) for doc_idx, score in ranked_docs]

    def __len__(self) -> int:
        return self.total_docs
