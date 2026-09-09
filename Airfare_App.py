from flask import Flask, render_template, jsonify, request
import pandas as pd
from datetime import datetime
import os

app = Flask(__name__)

# Load domestic airfare dataset
df = pd.read_excel('airfare_domestic.xlsx')
df['route'] = df['origin'] + '-' + df['destination']

CITY_MAP = {
    'DEL': 'Delhi (DEL) - IGI Airport',
    'BOM': 'Mumbai (BOM) - CSMIA',
    'BLR': 'Bengaluru (BLR) - Kempegowda Intl',
    'HYD': 'Hyderabad (HYD) - Rajiv Gandhi Intl',
    'CCU': 'Kolkata (CCU) - Netaji Subhash Chandra Bose Intl',
    'MAA': 'Chennai (MAA) - Chennai Intl',
    'PNQ': 'Pune (PNQ) - Pune Airport',
    'GOI': 'Goa (GOI / GOX) - Dabolim / Mopa',
    'AMD': 'Ahmedabad (AMD) - Sardar Vallabhbhai Patel Intl',
    'JAI': 'Jaipur (JAI) - Jaipur Intl',
    'LKO': 'Lucknow (LKO) - Chaudhary Charan Singh Intl',
    'COK': 'Kochi (COK) - Cochin Intl',
    'GAU': 'Guwahati (GAU) - Lokpriya Gopinath Bordoloi Intl',
    'PAT': 'Patna (PAT) - Jayprakash Narayan Intl',
    'IXC': 'Chandigarh (IXC) - Shaheed Bhagat Singh Intl'
}

DISTANCE_FACTORS = {
    'DEL-BOM': 1.0, 'BOM-DEL': 1.0,
    'BLR-HYD': 0.65, 'HYD-BLR': 0.65,
    'DEL-BLR': 1.25, 'BLR-DEL': 1.25,
    'BOM-BLR': 0.85, 'BLR-BOM': 0.85,
    'DEL-CCU': 1.15, 'CCU-DEL': 1.15,
    'BOM-GOI': 0.60, 'GOI-BOM': 0.60,
    'PNQ-DEL': 1.05, 'DEL-PNQ': 1.05,
    'AMD-DEL': 0.75, 'DEL-AMD': 0.75,
    'LKO-DEL': 0.55, 'DEL-LKO': 0.55,
    'COK-BOM': 0.95, 'BOM-COK': 0.95
}

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/api/airports')
def get_airports():
    return jsonify(CITY_MAP)

@app.route('/api/stats')
def get_stats():
    base_fare = df[df['advance_days'].isin([30, 45])]['total_fare'].mean()
    spot_fare = df[df['advance_days'] == 1]['total_fare'].mean()
    cpi_index = round((spot_fare / base_fare) * 100, 2)
    inflation_rate = round(cpi_index - 100, 2)
    airline_avg = df.groupby('airline')['total_fare'].mean().round(2).to_dict()
    
    return jsonify({
        'total_records': len(df),
        'base_fare': round(base_fare, 2),
        'spot_fare': round(spot_fare, 2),
        'cpi_index': cpi_index,
        'inflation_rate': inflation_rate,
        'routes': sorted(df['route'].unique().tolist()),
        'airline_avg': airline_avg
    })

@app.route('/api/route-trend')
def route_trend():
    route = request.args.get('route', 'DEL-BOM')
    filtered = df[df['route'] == route]
    if filtered.empty:
        filtered = df[df['route'] == 'DEL-BOM']
    trend = filtered.groupby('advance_days')['total_fare'].mean().round(2).to_dict()
    return jsonify({
        'route': route,
        'days': list(trend.keys()),
        'fares': list(trend.values())
    })

@app.route('/api/recommend', methods=['POST'])
def recommend_flights():
    data = request.json or {}
    origin = data.get('origin', 'BOM')
    dest = data.get('destination', 'DEL')
    travel_date_str = data.get('travel_date')
    cabin_class = data.get('cabin_class', 'economy')
    passengers = data.get('passengers', [])

    if not passengers:
        passengers = [{'age': 25, 'category': 'general'}]

    seat_count = len(passengers)
    validation_warnings = []
    evaluated_passengers = []

    for idx, p in enumerate(passengers, start=1):
        age = int(p.get('age', 25))
        category = p.get('category', 'general')
        discount_pct = 0.0
        label = "Standard Fare"

        if category == 'senior':
            if age < 60:
                validation_warnings.append(f"Passenger {idx}: Senior concession requires age 60+ (Passenger is {age}). Concession revoked.")
                category = 'general'
            else:
                discount_pct = 0.20
                label = "Senior Concession (20% Off)"
        elif category == 'student':
            if age < 12 or age > 26:
                validation_warnings.append(f"Passenger {idx}: Student concession requires age 12-26 (Passenger is {age}). Reverting to standard fare.")
                category = 'general'
            else:
                discount_pct = 0.15
                label = "Student Special (15% Off)"
        elif category == 'defense':
            if age < 18:
                validation_warnings.append(f"Passenger {idx}: Armed Forces concession requires age 18+ (Passenger is {age}). Reverting to general fare.")
                category = 'general'
            else:
                discount_pct = 0.25
                label = "Armed Forces Concession (25% Off)"

        evaluated_passengers.append({
            'passenger_num': idx,
            'age': age,
            'discount_pct': discount_pct,
            'label': label
        })

    target_route = f"{origin}-{dest}"
    matched = df[df['route'] == target_route].copy()
    is_synthesized = False
    route_scale = DISTANCE_FACTORS.get(target_route, 1.05)

    if matched.empty:
        matched = df[df['destination'] == dest].copy()
    if matched.empty:
        matched = df.copy()
        is_synthesized = True

    if travel_date_str:
        try:
            travel_date = datetime.strptime(travel_date_str, "%Y-%m-%d")
            lead_days = max(1, (travel_date - datetime.today()).days)
        except Exception:
            lead_days = 7
    else:
        lead_days = 7

    brackets = [1, 7, 15, 30, 45]
    closest_bracket = min(brackets, key=lambda x: abs(x - lead_days))
    bracket_df = matched[matched['advance_days'] == closest_bracket]
    if bracket_df.empty:
        bracket_df = matched

    cabin_multiplier = 2.4 if cabin_class == 'business' else 1.0

    deals = []
    for carrier, group in bracket_df.groupby('airline'):
        base_flight_fare = group['total_fare'].median() * (route_scale if is_synthesized else 1.0)
        base_seat_fare = round(base_flight_fare * cabin_multiplier, 2)
        
        passenger_breakdown = []
        total_trip_cost = 0.0

        for ep in evaluated_passengers:
            seat_fare = round(base_seat_fare * (1.0 - ep['discount_pct']), 2)
            total_trip_cost += seat_fare
            passenger_breakdown.append({
                'passenger': f"Passenger {ep['passenger_num']}",
                'age': ep['age'],
                'concession': ep['label'],
                'seat_fare': seat_fare
            })

        flight_num = group['flight_number'].iloc[0]
        segments = int(group['number_of_segments'].iloc[0])
        dep_time = str(group['departure_time'].iloc[0]).split('T')[-1][:5] if 'T' in str(group['departure_time'].iloc[0]) else "08:30"

        deals.append({
            'airline': carrier,
            'flight_number': f"{group['marketing_carrier'].iloc[0]}-{flight_num}",
            'segments': 'Non-Stop' if segments == 1 else f"{segments-1} Stop",
            'departure_time': dep_time,
            'base_fare_per_seat': base_seat_fare,
            'total_trip_cost': round(total_trip_cost, 2),
            'breakdown': passenger_breakdown,
            'lead_bracket': closest_bracket
        })

    deals.sort(key=lambda x: x['total_trip_cost'])
    best_deal = deals[0] if deals else None

    if lead_days <= 3:
        ai_recommendation = (
            f"⚠️ **High Surge Alert:** Booking {lead_days} day(s) before departure. "
            f"You are in the +75% dynamic spot surge window. **{best_deal['airline']}** ({best_deal['flight_number']}) "
            f"is currently lowest at ₹{best_deal['total_trip_cost']:,.2f} total for {seat_count} seat(s)."
        )
    elif lead_days <= 14:
        ai_recommendation = (
            f"✅ **Balanced Window:** Booking {lead_days} days ahead offers steady rates. "
            f"**{best_deal['airline']}** provides the optimal value at ₹{best_deal['total_trip_cost']:,.2f} total for {seat_count} passenger(s)."
        )
    else:
        ai_recommendation = (
            f"🌟 **Optimal Advance Booking:** At {lead_days} days advance, pricing sits at the baseline index. "
            f"**{best_deal['airline']}** is the highest-value option at ₹{best_deal['total_trip_cost']:,.2f}."
        )

    return jsonify({
        'route': target_route,
        'origin_city': CITY_MAP.get(origin, origin),
        'destination_city': CITY_MAP.get(dest, dest),
        'lead_days': lead_days,
        'seats': seat_count,
        'cabin_class': cabin_class.capitalize(),
        'validation_warnings': validation_warnings,
        'best_deal': best_deal,
        'all_deals': deals,
        'ai_recommendation': ai_recommendation
    })

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
