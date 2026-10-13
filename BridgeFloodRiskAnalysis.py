"""ArcGIS Pro script tool: bridge flood risk scoring.

Parameters
0. Input bridge feature layer / table (editable)          - Required, Input
1. Base year (Long)                                      - Optional, Input, default = current year
2. Updated input (Feature Layer / Table)                  - Derived, Output
   (reconfigure from Required Output; it is set to the input dataset)
3. Output charts folder (Folder)                          - Optional, Input
"""
# Workflow:
#   1. Read the required fields from the input table into a pandas DataFrame.
#   2. Score each bridge on age, remaining life (end of life minus base year) and
#      deck/beam material, sum the scores and classify into a risk category.
#   3. Append bridge_risk_score and risk_category fields to the input and
#      populate them (only selected rows are updated if the layer has a selection).
#   4. Optionally save summary charts and report summary statistics.
import datetime
import os
import arcpy
import pandas as pd

REQUIRED_FIELDS = ['condition', 'age', 'expected_end_of_life', 'deck_material', 'beam_type']
ID_FIELDS = ['structure_number']


def default_geodatabase():
    # Fall back through: project default GDB, current workspace, scratch GDB
    try:
        gdb = arcpy.mp.ArcGISProject("CURRENT").defaultGeodatabase
    except (OSError, RuntimeError):
        gdb = None
    return gdb or arcpy.env.workspace or arcpy.env.scratchGDB


def resolve_fields(table, wanted):
    """Map wanted names to actual field names, case-insensitively."""
    actual = {f.name.lower(): f.name for f in arcpy.ListFields(table)}
    missing = [w for w in wanted if w.lower() not in actual]
    if missing:
        raise ValueError(f"Input is missing required field(s): {', '.join(missing)}")
    return {w: actual[w.lower()] for w in wanted}


def load_table(table):
    # Read required fields (plus structure_number if present) via a cursor
    names = resolve_fields(table, REQUIRED_FIELDS)
    optional = {f.name.lower(): f.name for f in arcpy.ListFields(table)}
    ids = {w: optional[w.lower()] for w in ID_FIELDS if w.lower() in optional}
    oid_field = arcpy.Describe(table).OIDFieldName
    src = [oid_field] + list(ids.values()) + list(names.values())
    out = ['source_oid'] + list(ids.keys()) + list(names.keys())
    with arcpy.da.SearchCursor(table, src) as cur:
        return pd.DataFrame([list(r) for r in cur], columns=out)


# Scoring: higher = greater flood risk. Age, remaining life and material scores
# are summed (max 100).
def score_age(age):
    if age > 80: return 30
    elif age > 50: return 20
    elif age > 20: return 15
    return 5


def score_life(life):
    if life < 5: return 30
    elif life < 15: return 20
    elif life < 30: return 15
    return 0


def score_material(deck, beam):
    score = 10  # Default for concrete/unknown-but-heavy
    if pd.notnull(deck) and 'Wood' in str(deck):
        score = max(score, 40)
    if pd.notnull(beam) and ('Wood' in str(beam) or 'Timber' in str(beam)):
        score = max(score, 40)
    if pd.notnull(beam) and 'Steel' in str(beam):
        score = max(score, 20)
    if pd.isnull(deck) and pd.isnull(beam):
        score = max(score, 20)
    return score


# Total score thresholds: >=65 High, >=45 Medium, otherwise Low
def classify_risk(score):
    if score >= 65: return 'High Risk'
    elif score >= 45: return 'Medium Risk'
    return 'Low Risk'


def score_bridges(df, base_year):
    # Apply each scoring rule, then total and classify
    df['remaining_life'] = df['expected_end_of_life'] - base_year
    df['age_risk'] = df['age'].apply(score_age)
    df['life_risk'] = df['remaining_life'].apply(score_life)
    df['material_risk'] = df.apply(lambda x: score_material(x['deck_material'], x['beam_type']), axis=1)
    df['bridge_risk_score'] = df['age_risk'] + df['life_risk'] + df['material_risk']
    df['risk_category'] = df['bridge_risk_score'].apply(classify_risk)
    return df


def update_input(df, table):
    # Append the result fields to the input (if absent) and populate them by OID
    existing = {f.name.lower(): f for f in arcpy.ListFields(table)}
    if 'bridge_risk_score' not in existing:
        arcpy.management.AddField(table, 'bridge_risk_score', 'LONG')
    if 'risk_category' not in existing:
        arcpy.management.AddField(table, 'risk_category', 'TEXT', field_length=20)
    # Re-list so the real (possibly differently cased) names are used
    actual = {f.name.lower(): f.name for f in arcpy.ListFields(table)}
    score_field = actual['bridge_risk_score']
    cat_field = actual['risk_category']

    results = {int(oid): (int(s), c) for oid, s, c in
               zip(df['source_oid'], df['bridge_risk_score'], df['risk_category'])}
    oid_field = arcpy.Describe(table).OIDFieldName

    updated = 0
    with arcpy.da.UpdateCursor(table, [oid_field, score_field, cat_field]) as cur:
        for oid, _, _ in cur:
            if oid in results:
                cur.updateRow([oid, *results[oid]])
                updated += 1
    return updated


def save_charts(df, folder):
    # Score histogram and category bar chart (non-interactive backend for GP use)
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    os.makedirs(folder, exist_ok=True)
    fig, ax = plt.subplots(figsize=(10, 6))
    ax.hist(df['bridge_risk_score'], bins=20, color='teal')
    ax.set(title='Distribution of Flood Risk Scores for Bridges',
           xlabel='Risk Score (0 - 100)', ylabel='Number of Bridges')
    fig.savefig(os.path.join(folder, 'flood_risk_distribution.png'))
    plt.close(fig)

    order = ['Low Risk', 'Medium Risk', 'High Risk']
    counts = df['risk_category'].value_counts().reindex(order, fill_value=0)
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.bar(order, counts.values, color='firebrick')
    ax.set(title='Bridge Flood Risk Categories', ylabel='Count', xlabel='Risk Category')
    fig.savefig(os.path.join(folder, 'flood_risk_categories.png'))
    plt.close(fig)


def main():
    in_table = arcpy.GetParameterAsText(0)
    charts_folder = arcpy.GetParameterAsText(3)
    base_year = int(arcpy.GetParameterAsText(1) or datetime.date.today().year)

    # Score, write results, then optional charts and summary
    df = score_bridges(load_table(in_table), base_year)
    arcpy.AddMessage(f"Scored {len(df)} bridges using base year {base_year}.")

    updated = update_input(df, in_table)
    arcpy.SetParameterAsText(2, in_table)
    arcpy.AddMessage(f"Updated {updated} rows in {in_table} "
                     "(added risk_category and bridge_risk_score).")

    if charts_folder:
        save_charts(df, charts_folder)
        arcpy.AddMessage(f"Charts saved to {charts_folder}")

    for cat, n in df['risk_category'].value_counts().items():
        arcpy.AddMessage(f"{cat}: {n}")
    s = df['bridge_risk_score']
    arcpy.AddMessage(f"Max score: {s.max()}, Min score: {s.min()}, Mean score: {s.mean():.1f}")


if __name__ == '__main__':
    main()




