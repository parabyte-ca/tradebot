"""LightGBM signal model: training, prediction, and persistence.

Labelling: triple-barrier method
  - Upper barrier: +TAKE_PROFIT_PCT (default 4%)
  - Lower barrier: -STOP_LOSS_PCT   (default 2%)
  - Time barrier:  HOLDING_DAYS     (default 5 trading days)
  Label = 1 (up) if upper barrier hit first, else 0.

Validation: purged walk-forward CV with a 20-day embargo to prevent
look-ahead bias from overlapping holding periods.

Retraining: APScheduler weekly cron job.
"""

import logging
import os
import pickle
from typing import Optional, Tuple

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

from config.settings import get_settings

logger = logging.getLogger(__name__)

FEATURE_COLS = [
    "rsi_14", "macd", "macd_signal", "macd_hist", "bb_width_20", "atr_14",
    "volume_zscore", "price_vs_sma20", "price_vs_sma50", "price_vs_sma200",
    "ret_1w", "ret_1m", "ret_3m", "mean_rev_atr", "sentiment_7d",
    "vix_level", "spy_above_200",
]


# ---------------------------------------------------------------------------
# Triple-barrier labelling
# ---------------------------------------------------------------------------

def _triple_barrier_labels(
    close: pd.Series,
    stop_pct: float,
    tp_pct: float,
    holding_days: int,
) -> pd.Series:
    """Generate binary labels using the triple-barrier method.

    Returns a Series of {0, 1} aligned with *close*, NaN for last
    *holding_days* rows where the label cannot be computed.
    """
    labels = pd.Series(np.nan, index=close.index)
    for i in range(len(close) - holding_days):
        entry = close.iloc[i]
        window = close.iloc[i + 1 : i + 1 + holding_days]
        upper = entry * (1 + tp_pct)
        lower = entry * (1 - stop_pct)

        hit_upper = window[window >= upper].index
        hit_lower = window[window <= lower].index

        if hit_upper.empty and hit_lower.empty:
            # Time barrier — label as 0 (no clear win)
            labels.iloc[i] = 0
        elif hit_upper.empty:
            labels.iloc[i] = 0
        elif hit_lower.empty:
            labels.iloc[i] = 1
        else:
            # Whichever barrier is hit first
            labels.iloc[i] = 1 if hit_upper[0] < hit_lower[0] else 0

    return labels


# ---------------------------------------------------------------------------
# Purged walk-forward cross-validation
# ---------------------------------------------------------------------------

def _purged_wf_cv(
    X: pd.DataFrame,
    y: pd.Series,
    n_folds: int = 5,
    embargo_days: int = 20,
) -> list[float]:
    """Purged walk-forward CV.  Returns list of out-of-fold AUC scores."""
    n = len(X)
    fold_size = n // (n_folds + 1)
    aucs = []

    for fold in range(n_folds):
        train_end = fold_size * (fold + 1)
        test_start = train_end + embargo_days
        test_end = test_start + fold_size

        if test_end > n:
            break

        X_train = X.iloc[:train_end]
        y_train = y.iloc[:train_end]
        X_test = X.iloc[test_start:test_end]
        y_test = y.iloc[test_start:test_end]

        # Drop rows without labels
        mask_train = y_train.notna()
        mask_test = y_test.notna()

        if mask_train.sum() < 50 or mask_test.sum() < 10:
            continue

        model = _fit_lgbm(X_train[mask_train], y_train[mask_train])
        preds = model.predict(X_test[mask_test])
        auc = roc_auc_score(y_test[mask_test], preds)
        aucs.append(auc)
        logger.info("Fold %d AUC: %.4f", fold + 1, auc)

    return aucs


def _fit_lgbm(X: pd.DataFrame, y: pd.Series) -> lgb.LGBMClassifier:
    """Fit a LightGBM binary classifier."""
    model = lgb.LGBMClassifier(
        n_estimators=300,
        learning_rate=0.05,
        num_leaves=31,
        min_child_samples=20,
        subsample=0.8,
        colsample_bytree=0.8,
        reg_alpha=0.1,
        reg_lambda=0.1,
        random_state=42,
        n_jobs=-1,
        verbose=-1,
    )
    model.fit(X.fillna(0), y)
    return model


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def train_model(df: pd.DataFrame) -> Tuple[lgb.LGBMClassifier, list[float]]:
    """Train the LightGBM model on *df* using triple-barrier labels and WF-CV.

    Args:
        df: DataFrame with FEATURE_COLS columns and a 'close' column,
            sorted ascending by date.

    Returns:
        (trained_model, list_of_fold_aucs)
    """
    cfg = get_settings()

    close = df["close"]
    labels = _triple_barrier_labels(
        close,
        stop_pct=cfg.stop_loss_pct,
        tp_pct=cfg.take_profit_pct,
        holding_days=cfg.holding_days,
    )

    feature_cols = [c for c in FEATURE_COLS if c in df.columns]
    X = df[feature_cols]
    y = labels

    valid_mask = y.notna()
    X_valid = X[valid_mask]
    y_valid = y[valid_mask]

    aucs = _purged_wf_cv(X_valid, y_valid)
    mean_auc = np.mean(aucs) if aucs else float("nan")
    logger.info("Walk-forward CV mean AUC: %.4f over %d folds", mean_auc, len(aucs))

    final_model = _fit_lgbm(X_valid, y_valid)
    return final_model, aucs


def predict(model: lgb.LGBMClassifier, features_df: pd.DataFrame) -> pd.Series:
    """Return predicted up-probability for each row of *features_df*.

    Args:
        model:       Trained LGBMClassifier.
        features_df: DataFrame with FEATURE_COLS (may have extra columns).

    Returns:
        pd.Series of float probabilities, indexed like *features_df*.
    """
    feature_cols = [c for c in FEATURE_COLS if c in features_df.columns]
    X = features_df[feature_cols].fillna(0)
    probs = model.predict_proba(X)[:, 1]
    return pd.Series(probs, index=features_df.index)


def save_model(model: lgb.LGBMClassifier, path: Optional[str] = None) -> str:
    """Pickle the model to *path* (defaults to MODEL_PATH/lgbm_model.pkl)."""
    if path is None:
        cfg = get_settings()
        os.makedirs(cfg.model_path, exist_ok=True)
        path = os.path.join(cfg.model_path, "lgbm_model.pkl")
    with open(path, "wb") as fh:
        pickle.dump(model, fh)
    logger.info("Model saved to %s", path)
    return path


def load_model(path: Optional[str] = None) -> Optional[lgb.LGBMClassifier]:
    """Load a pickled LightGBM model from *path*.

    Returns None if the file does not exist.
    """
    if path is None:
        cfg = get_settings()
        path = os.path.join(cfg.model_path, "lgbm_model.pkl")
    if not os.path.exists(path):
        logger.warning("No model found at %s", path)
        return None
    with open(path, "rb") as fh:
        model = pickle.load(fh)
    logger.info("Model loaded from %s", path)
    return model
