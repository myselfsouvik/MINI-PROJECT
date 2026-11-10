# import pandas as pd

# # Load Animal Bites dataset
# file_path = "data/tabular/Health_AnimalBites.csv"

# df = pd.read_csv(file_path)

# print("\n========== DATASET LOADED ==========")
# print("Rows:", df.shape[0])
# print("Columns:", df.shape[1])

# print("\n========== COLUMN NAMES ==========")
# print(df.columns.tolist())

# print("\n========== FIRST 5 ROWS ==========")
# print(df.head())

# print("\n========== DATA TYPES ==========")
# print(df.dtypes)

# print("\n========== MISSING VALUES ==========")
# print(df.isnull().sum())

# print("\n========== DUPLICATES ==========")
# print("Duplicate rows:", df.duplicated().sum())

# print("\n========== RESULTS VALUES ==========")
# print(df["ResultsIDDesc"].value_counts(dropna=False))

# print("\n========== SPECIES VALUES ==========")
# print(df["SpeciesIDDesc"].value_counts(dropna=False))

# print("\n========== DOG RABIES RESULTS ==========")

# dog_data = df[df["SpeciesIDDesc"] == "DOG"]

# print(dog_data["ResultsIDDesc"].value_counts(dropna=False))

# print("\n========== INSPECTION COMPLETE ==========")


import pandas as pd
from sklearn.model_selection import train_test_split

# ==========================================
# 1. LOAD DATASET
# ==========================================

file_path = "data/tabular/Health_AnimalBites.csv"

df = pd.read_csv(file_path)

print("\n========== ORIGINAL DATASET ==========")
print("Rows:", df.shape[0])
print("Columns:", df.shape[1])


# ==========================================
# 2. KEEP DOG RECORDS ONLY
# ==========================================

df = df[df["SpeciesIDDesc"] == "DOG"].copy()

print("\n========== DOG DATA ==========")
print("Dog records:", len(df))


# ==========================================
# 3. SELECT RABIES RESULT
# ==========================================

print("\n========== ORIGINAL RABIES RESULTS ==========")
print(df["ResultsIDDesc"].value_counts(dropna=False))


# ==========================================
# 4. REMOVE UNKNOWN AND MISSING TARGETS
# ==========================================

df = df[
    df["ResultsIDDesc"].isin(["POSITIVE", "NEGATIVE"])
].copy()

print("\n========== AFTER TARGET CLEANING ==========")
print("Usable records:", len(df))

print(df["ResultsIDDesc"].value_counts())


# ==========================================
# 5. REMOVE DUPLICATES
# ==========================================

before_duplicates = len(df)

df = df.drop_duplicates()

after_duplicates = len(df)

print("\n========== DUPLICATE REMOVAL ==========")
print("Duplicates removed:", before_duplicates - after_duplicates)
print("Records remaining:", after_duplicates)


# ==========================================
# 6. CREATE BINARY TARGET
# ==========================================

df["target"] = df["ResultsIDDesc"].map({
    "NEGATIVE": 0,
    "POSITIVE": 1
})

print("\n========== TARGET ==========")
print(df["target"].value_counts())


# ==========================================
# 7. CHECK TARGET BALANCE
# ==========================================

print("\n========== TARGET DISTRIBUTION ==========")

negative = (df["target"] == 0).sum()
positive = (df["target"] == 1).sum()

print("Negative:", negative)
print("Positive:", positive)


# ==========================================
# 8. DATASET DECISION
# ==========================================

if positive < 2:
    print("\n========== DATASET WARNING ==========")
    print("Only one positive dog record is available.")
    print("A valid stratified 80:20 train/test split")
    print("cannot preserve the positive class in both sets.")
    print("SMOTE should NOT be applied to this dataset.")


# ==========================================
# 9. SAVE CLEANED DATA
# ==========================================

df.to_csv(
    "data/tabular/cleaned_animal_bites_dogs.csv",
    index=False
)

print("\n========== CLEANED DATA SAVED ==========")
print("File:")
print("data/tabular/cleaned_animal_bites_dogs.csv")