"""
Module for calculating candidate match scores based on defined rules.
"""
import logging
from typing import Any, Dict, List, Optional, Union

logger = logging.getLogger(__name__)

# --- Helper Function ---
def _safe_get_value(data: Optional[Dict], path: str, default: Any = None) -> Any:
    """Safely gets a value from a nested dictionary using dot notation path."""
    if not data or not path:
        return default
    keys = path.split('.')
    value = data
    try:
        for key in keys:
            if isinstance(value, dict):
                value = value.get(key)
            else: # Handle cases where intermediate path is not a dict
                 return default
            if value is None:
                return default
        return value
    except Exception as e:
        logger.warning(f"Error accessing path '{path}' in data: {e}")
        return default

# --- Scoring Logic Implementations ---

def calculate_range_match_score(required_value: Optional[Union[int, float]],
                                candidate_value: Optional[Union[int, float]],
                                params: Dict[str, Any]) -> float:
    """
    Calculates score based on how close a candidate's numeric value is to a required range.
    Handles minimum requirement matching with bonus for exceeding.

    Args:
        required_value: The target numeric value (e.g., minimum years of experience).
        candidate_value: The candidate's numeric value.
        params: Dictionary containing calculation parameters:
            - exact_match_score (float): Score for meeting the minimum requirement (default: 1.0).
            - tolerance_years (int/float): Allowed deviation BELOW required_value (default: 0).
            - score_decay_rate (float): Score reduction per year below tolerance (default: 0.1).
            - min_score (float): Minimum possible score (default: 0.0).
            - bonus_rate_per_year (float): Bonus score added per year *above* required_value (default: 0.05).
            - max_score_factor (float): Maximum score as a factor of exact_match_score (e.g., 1.5 means max score is 150% of base) (default: 1.5).

    Returns:
        The calculated score (float).
    """
    base_score = params.get('exact_match_score', 1.0)
    tolerance = params.get('tolerance_years', 0)
    decay_rate = params.get('score_decay_rate', 0.1)
    min_score = params.get('min_score', 0.0)
    bonus_rate = params.get('bonus_rate_per_year', 0.05)
    max_factor = params.get('max_score_factor', 1.5)
    max_score = base_score * max_factor

    if required_value is None or candidate_value is None:
        logger.debug("Range match: Missing required or candidate value.")
        # If requirement is missing, should everyone get a default score?
        # If candidate value is missing, they likely get min_score.
        return min_score

    try:
        # Use minimum requirement specified by LLM
        req_val = float(required_value)
        cand_val = float(candidate_value)
    except (ValueError, TypeError):
        logger.warning(f"Range match: Could not convert values to float. Req: {required_value}, Cand: {candidate_value}")
        return min_score

    if cand_val >= req_val:
        # Candidate meets or exceeds minimum requirement
        diff = cand_val - req_val
        # Start with base score and add bonus for exceeding years
        score = base_score + (diff * bonus_rate * base_score) # Bonus scaled by base score
        # 不限制最大值，以区分更多经验差异
        final_score = score
        logger.debug(f"Range match (>= req): Req={req_val}, Cand={cand_val}, Diff={diff}, Score (uncapped)={final_score:.2f}")
        return final_score
    else:
        # Candidate is below minimum requirement
        diff = req_val - cand_val
        if diff <= tolerance:
            # Below requirement but within tolerance: decay from base score
            score = base_score - (diff * decay_rate * base_score) # Decay scaled by base score
            final_score = max(min_score, score)
            logger.debug(f"Range match (< req, within tolerance): Req={req_val}, Cand={cand_val}, Diff={diff}, Score={final_score:.2f}")
            return final_score
        else:
            # Below requirement and outside tolerance: decay further
            # Score after tolerance decay
            score_at_tolerance_edge = base_score - (tolerance * decay_rate * base_score)
            # Additional decay for years beyond tolerance (potentially heavier)
            additional_decay_years = diff - tolerance
            # Using 1.5 times the decay rate beyond tolerance, scaled by base score
            score = score_at_tolerance_edge - (additional_decay_years * decay_rate * 1.5 * base_score)
            final_score = max(min_score, score)
            logger.debug(f"Range match (< req, outside tolerance): Req={req_val}, Cand={cand_val}, Diff={diff}, Score={final_score:.2f}")
            return final_score


def calculate_keyword_overlap_score(required_list: Optional[List[str]],
                                    candidate_list: Optional[List[str]],
                                    params: Dict[str, Any]) -> float:
    """
    Calculates score based on the overlap between required keywords and candidate keywords.

    Args:
        required_list: List of required keywords/skills.
        candidate_list: List of candidate's keywords/skills.
        params: Dictionary containing calculation parameters:
            - score_per_match (float): Score awarded for each matching keyword (default: 1.0).
            - max_score (float): Maximum possible score for this dimension (optional, defaults to score_per_match * len(required_list)).
            # Add params for core vs normal skills later if needed

    Returns:
        The calculated score (float).
    """
    score_per_match = params.get('score_per_match', 1.0)
    default_max_score = len(required_list) * score_per_match if required_list else 0
    max_score = params.get('max_score', default_max_score)

    if not required_list:
        logger.debug("Keyword overlap: No required keywords specified.")
        return 1.0 # If nothing is required, it's a perfect match? Or 0.0? Consider context. Let's assume 1.0 (full score).

    if not candidate_list:
        logger.debug("Keyword overlap: Candidate list is empty.")
        return 0.0

    # Ensure lists contain strings and handle potential errors
    try:
        req_set = set(str(item).lower() for item in required_list if item)
        cand_set = set(str(item).lower() for item in candidate_list if item)
    except Exception as e:
        logger.warning(f"Keyword overlap: Error processing lists. Req: {required_list}, Cand: {candidate_list}. Error: {e}")
        return 0.0

    matches = req_set.intersection(cand_set)
    score = len(matches) * score_per_match

    # Normalize score relative to the number of required items, capped at 1.0?
    # Or cap at max_score from params?
    # Current approach: score capped by max_score

    normalized_score = score
    if max_score > 0:
         # Cap the score relative to the max_score if max_score is defined and positive
         # Calculate proportion relative to the theoretical max based on required items
         theoretical_max = len(req_set) * score_per_match
         if theoretical_max > 0:
              normalized_score = min(score / theoretical_max, 1.0) * max_score # Scale to max_score proportionally
         else:
              normalized_score = max_score # If no required items, give max score? Or 0?

    # Let's simplify: Score is based on matches, capped by max_score.
    final_score = min(score, max_score) if max_score is not None else score

    # Alternative normalization: Score as a percentage of required items matched
    # if len(req_set) > 0:
    #    final_score = len(matches) / len(req_set)
    # else:
    #    final_score = 1.0 # Or 0.0?

    logger.debug(f"Keyword overlap: Required: {req_set}, Candidate: {cand_set}, Matches: {matches}, Score: {final_score}")
    # Using the simpler capping approach for now.
    return final_score


def calculate_exact_match_score(required_value: Optional[Any],
                                candidate_value: Optional[Any],
                                params: Dict[str, Any]) -> float:
    """
    Calculates score based on exact match between required and candidate values.

    Args:
        required_value: The required value.
        candidate_value: The candidate's value.
        params: Dictionary containing calculation parameters:
            - match_score (float): Score for an exact match (default: 1.0).
            - mismatch_score (float): Score for a mismatch (default: 0.0).
            - case_sensitive (bool): Whether the match should be case-sensitive (default: False).

    Returns:
        match_score or mismatch_score.
    """
    match_score = params.get('match_score', 1.0)
    mismatch_score = params.get('mismatch_score', 0.0)
    case_sensitive = params.get('case_sensitive', False)

    if required_value is None:
         logger.debug("Exact match: No required value specified.")
         # If nothing is required, maybe it's always a match? Or depends?
         # Let's assume if nothing required, score is max.
         return match_score

    if candidate_value is None:
        logger.debug("Exact match: Candidate value is missing.")
        return mismatch_score

    req_str = str(required_value)
    cand_str = str(candidate_value)

    if case_sensitive:
        match = req_str == cand_str
    else:
        match = req_str.lower() == cand_str.lower()

    score = match_score if match else mismatch_score
    logger.debug(f"Exact match: Required: '{req_str}', Candidate: '{cand_str}', CaseSensitive: {case_sensitive}, Match: {match}, Score: {score}")
    return score


def calculate_keyword_presence_score(required_list: Optional[List[str]],
                                     candidate_list: Optional[List[str]],
                                     params: Dict[str, Any]) -> float:
    """
    Calculates score based on the presence of required keywords in the candidate's list.
    Similar to overlap but often used for boolean checks (e.g., has cert X?).

    Args:
        required_list: List of required keywords/certificates.
        candidate_list: List of candidate's keywords/certificates.
        params: Dictionary containing calculation parameters:
            - score_per_match (float): Score awarded for each matching keyword found (default: 1.0).
            - max_score (float): Maximum possible score for this dimension (default: 1.0). Ensures score doesn't exceed 1.0 even if multiple required items are present.

    Returns:
        The calculated score (float, typically capped at max_score).
    """
    score_per_match = params.get('score_per_match', 1.0)
    # Default max_score is 1.0 for presence checks (e.g., does the candidate have *any* of the required certs?)
    # If you want score based on *how many* required certs they have, adjust config/logic.
    max_score = params.get('max_score', 1.0)

    if not required_list:
        logger.debug("Keyword presence: No required items specified.")
        return max_score # Assumes if nothing required, condition is met.

    if not candidate_list:
        logger.debug("Keyword presence: Candidate list is empty.")
        return 0.0

    try:
        req_set = set(str(item).lower() for item in required_list if item)
        cand_set = set(str(item).lower() for item in candidate_list if item)
    except Exception as e:
        logger.warning(f"Keyword presence: Error processing lists. Req: {required_list}, Cand: {candidate_list}. Error: {e}")
        return 0.0

    matches = req_set.intersection(cand_set)
    score = len(matches) * score_per_match

    # Cap the score at max_score
    final_score = min(score, max_score) if max_score is not None else score

    logger.debug(f"Keyword presence: Required: {req_set}, Candidate: {cand_set}, Matches: {matches}, Score: {final_score}")
    return final_score


# --- Main Scoring Function ---

SCORE_FUNCTION_MAP = {
    "range_match": calculate_range_match_score,
    "keyword_overlap": calculate_keyword_overlap_score,
    "exact_match": calculate_exact_match_score,
    "keyword_presence": calculate_keyword_presence_score,
    # Add mappings for other logic types here
}

def calculate_score_for_dimension(dimension_config: Dict[str, Any],
                                  query_criteria: Dict[str, Any],
                                  candidate_data: Dict[str, Any]) -> float:
    """
    Calculates the score for a single dimension based on its configuration.

    Args:
        dimension_config: Configuration dict for the specific dimension (from scoring_rules.dimensions).
        query_criteria: The parsed query criteria dictionary from LLM.
        candidate_data: The candidate's data dictionary (including 'query_tags').

    Returns:
        The calculated score for this dimension (float, typically between 0 and dimension weight/max score).
        Returns 0.0 if the dimension is disabled or scoring fails.
    """
    if not dimension_config.get('enabled', False):
        return 0.0

    logic_config = dimension_config.get('logic')
    if not logic_config:
        logger.warning(f"Dimension '{dimension_config.get('name', 'Unknown')}' has no logic configuration.")
        return 0.0

    logic_type = logic_config.get('type')
    score_func = SCORE_FUNCTION_MAP.get(logic_type)
    if not score_func:
        logger.warning(f"Unsupported scoring logic type: '{logic_type}'")
        return 0.0

    # Safely get required and candidate values using paths from config
    req_path = logic_config.get('required_value_path')
    cand_path = logic_config.get('candidate_value_path')

    # Assume query_criteria structure like {'criteria': {...}}
    # Assume candidate_data has top-level fields and 'query_tags'
    required_value = _safe_get_value(query_criteria, req_path.replace('query.criteria.', '')) if req_path else None
    candidate_value = _safe_get_value(candidate_data, cand_path.replace('candidate.', '')) if cand_path else None

    # Log extracted values for debugging
    # logger.debug(f"Scoring Dimension '{dimension_config.get('name', logic_type)}': Req path='{req_path}' val={required_value}, Cand path='{cand_path}' val={candidate_value}")


    params = logic_config.get('params', {})

    try:
        # Calculate raw score based on logic type (usually normalized 0-1 or similar)
        raw_score = score_func(required_value, candidate_value, params)

        # Apply weight - weight acts as the max score for this dimension here.
        weight = dimension_config.get('weight', 0)
        # Assume raw_score is normalized between 0 and 1 (or max defined in params).
        # The final score for the dimension is scaled by its weight.
        # E.g., if weight=30 and raw_score=0.8, final dimension score = 24.
        final_score = raw_score * weight

        return final_score

    except Exception as e:
        logger.error(f"Error calculating score for dimension type '{logic_type}': {e}", exc_info=True)
        return 0.0 