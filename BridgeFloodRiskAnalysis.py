"""ArcGIS Pro script tool: bridge flood risk scoring.

Parameters
0. Input bridge table (Table View / feature class / CSV)  - Required, Input
1. Base year (Long)                                      - Optional, Input, default = current year
2. Output risk table (Table)                              - Required, Output
   Set the parameter's default to the project default geodatabase, or pass
   just a table name to have it created in the default geodatabase.
3. Output charts folder (Folder)                          - Optional, Input
"""
# Workflow:
#   1. Read the required fields from the input table into a pandas DataFrame.
#   2. Score each bridge on age, remaining life (end of life minus base year) and
#      deck/beam material, sum the scores and classify into a risk category.
#   3. Write the results to a new table (default geodatabase if no path given).
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
    df['total_flood_risk_score'] = df['age_risk'] + df['life_risk'] + df['material_risk']
    df['risk_category'] = df['total_flood_risk_score'].apply(classify_risk)
    return df


def write_table(df, out_path):
    # Create the output table, add typed fields, then insert one row per bridge
    out_dir, out_name = os.path.split(out_path)
    if not out_dir:
        out_dir = default_geodatabase()
    arcpy.management.CreateTable(out_dir, out_name)
    out_path = os.path.join(out_dir, out_name)

    text = [('structure_number', 50), ('condition', 50), ('deck_material', 100),
            ('beam_type', 100), ('risk_category', 20)]
    for name, length in text:
        if name in df.columns:
            arcpy.management.AddField(out_path, name, 'TEXT', field_length=length)
    arcpy.management.AddField(out_path, 'source_oid', 'LONG')
    arcpy.management.AddField(out_path, 'age', 'DOUBLE')
    arcpy.management.AddField(out_path, 'expected_end_of_life', 'DOUBLE')
    arcpy.management.AddField(out_path, 'total_flood_risk_score', 'LONG')

    cols = [c for c in ['source_oid', 'structure_number', 'condition', 'age', 'expected_end_of_life',
                        'deck_material', 'beam_type', 'total_flood_risk_score', 'risk_category']
            if c in df.columns]

    # Convert pandas/numpy NaN and scalar types to values the cursor accepts
    def clean(v):
        if pd.isnull(v):
            return None
        return v.item() if hasattr(v, 'item') else v

    with arcpy.da.InsertCursor(out_path, cols) as cur:
        for row in df[cols].itertuples(index=False):
            cur.insertRow([clean(v) for v in row])
    return out_path


def save_charts(df, folder):
    # Score histogram and category bar chart (non-interactive backend for GP use)
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    os.makedirs(folder, exist_ok=True)
    fig, ax = plt.subplots(figsize=(10, 6))
    ax.hist(df['total_flood_risk_score'], bins=20, color='teal')
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
    out_table = arcpy.GetParameterAsText(2)
    charts_folder = arcpy.GetParameterAsText(3)
    base_year = int(arcpy.GetParameterAsText(1) or datetime.date.today().year)

    # Score, write results, then optional charts and summary
    df = score_bridges(load_table(in_table), base_year)
    arcpy.AddMessage(f"Scored {len(df)} bridges using base year {base_year}.")

    result = write_table(df, out_table)
    arcpy.SetParameterAsText(2, result)
    arcpy.AddMessage(f"Output table: {result}")

    if charts_folder:
        save_charts(df, charts_folder)
        arcpy.AddMessage(f"Charts saved to {charts_folder}")

    for cat, n in df['risk_category'].value_counts().items():
        arcpy.AddMessage(f"{cat}: {n}")
    s = df['total_flood_risk_score']
    arcpy.AddMessage(f"Max score: {s.max()}, Min score: {s.min()}, Mean score: {s.mean():.1f}")


if __name__ == '__main__':
    main()




