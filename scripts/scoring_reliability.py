#!/usr/bin/env python3
"""
Scoring function for Vision geocoding reliability.
Usage: score = predict_reliability(vision_features_dict) → {'tier': 'TRUSTED'|'REVIEW'|'REJECT', 'proba': float}
"""
import pickle, numpy as np

FEATURE_COLS = ['n_street_signs', 'n_shop_signs', 'n_landmarks', 'n_building_numbers', 'n_metro_bus', 'n_other_clues', 'n_total_clues', 'has_district', 'has_postcode', 'has_address', 'reasoning_length', 'address_length', 'address_has_number', 'address_has_business', 'geo_success', 'distance_to_center_km', 'distance_to_district_km', 'district_geocodes', 'city_coherent']
CONF_MAP = {'LOW': 0, 'MEDIUM': 1, 'HIGH': 2}

def extract_features(r):
    feats = []
    for col in FEATURE_COLS:
        try: feats.append(float(r.get(col, '0')))
        except: feats.append(0.0)
    conf_ord = CONF_MAP.get(r.get('confidence', 'LOW'), 0)
    n_signs = float(r.get('n_street_signs', 0))
    feats.append(conf_ord)
    feats.append(n_signs * conf_ord)
    feats.append(1.0 if n_signs > 0 and conf_ord >= 1 else 0.0)
    feats.append(float(r.get('address_has_number', 0)) * conf_ord)
    reasoning_len = max(float(r.get('reasoning_length', 1)), 1)
    feats.append(float(r.get('n_total_clues', 0)) / reasoning_len * 100)
    return feats

def predict_reliability(features_dict, model_path='geocoding_reliability_model.pkl'):
    with open(model_path, 'rb') as f:
        data = pickle.load(f)
    model = data['model']
    X = np.array([extract_features(features_dict)])
    proba = model.predict_proba(X)[0, 1]
    if proba >= 0.70:
        tier = 'TRUSTED'
    elif proba >= 0.45:
        tier = 'REVIEW'
    else:
        tier = 'REJECT'
    return {'tier': tier, 'proba': round(float(proba), 3)}

if __name__ == '__main__':
    # Example
    example = {
        'n_street_signs': '2', 'n_shop_signs': '1', 'n_landmarks': '0',
        'n_building_numbers': '1', 'n_metro_bus': '0', 'n_other_clues': '0',
        'n_total_clues': '4', 'has_district': '1', 'has_postcode': '1',
        'has_address': '1', 'reasoning_length': '450', 'address_length': '35',
        'address_has_number': '1', 'address_has_business': '0',
        'geo_success': '1', 'distance_to_center_km': '2.1',
        'distance_to_district_km': '0.8', 'district_geocodes': '1',
        'city_coherent': '1', 'confidence': 'HIGH',
    }
    result = predict_reliability(example)
    print(f"Prediction: {result}")
