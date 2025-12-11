from flask import Flask, request, jsonify
import requests
from bs4 import BeautifulSoup
import re
import warnings
from bs4 import XMLParsedAsHTMLWarning
from time import sleep, time
from datetime import datetime
import sys
import traceback

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

app = Flask(__name__)

CACHE = {}
CACHE_TTL = 3600

def get_headers():
    return {"User-Agent": "Andres Garcia andres@realemail.com"}


def get_cik(ticker):
    try:
        url = "https://www.sec.gov/files/company_tickers.json"
        r = requests.get(url, headers=get_headers(), timeout=10)
        r.raise_for_status()
        mapping = r.json()
        for v in mapping.values():
            if v["ticker"].upper() == ticker.upper():
                return str(v["cik_str"]).zfill(10)
        return None
    except Exception:
        return None


def get_company_info(cik):
    try:
        url = f"https://data.sec.gov/submissions/CIK{cik}.json"
        r = requests.get(url, headers=get_headers(), timeout=10)
        r.raise_for_status()
        data = r.json()
        return {
            "name": data.get("name"),
            "sic": data.get("sic"),
            "sic_description": data.get("sicDescription"),
            "category": data.get("category"),
            "fiscal_year_end": data.get("fiscalYearEnd")
        }
    except:
        return {}


def detect_industry(sic, sic_desc):
    if not sic:
        return "General"

    sic = str(sic)
    desc_lower = (sic_desc or "").lower()

    if sic.startswith("60") or "bank" in desc_lower:
        return "Bank"
    if sic == "6798" or "reit" in desc_lower or "real estate investment" in desc_lower:
        return "REIT"
    if sic.startswith("63") or sic.startswith("64") or "insurance" in desc_lower:
        return "Insurance"
    if sic.startswith("49") or "utility" in desc_lower or "electric" in desc_lower:
        return "Utility"
    if sic.startswith("13") or sic.startswith("29") or "oil" in desc_lower or "gas" in desc_lower:
        return "Energy"
    if sic.startswith("35") or sic.startswith("36") or sic.startswith("73") or "software" in desc_lower:
        return "Technology"
    if sic.startswith("28") or sic.startswith("80") or "pharmaceutical" in desc_lower or "health" in desc_lower:
        return "Healthcare"
    if sic.startswith("52") or sic.startswith("53") or sic.startswith("54") or sic.startswith("56") or sic.startswith("59"):
        return "Retail"
    if sic.startswith("20") or sic.startswith("30") or sic.startswith("34") or sic.startswith("37"):
        return "Manufacturing"
    return "General"


def extract_xbrl_data_optimized(cik):
    """
    Fetch annual facts from SEC companyfacts CIK JSON.
    Returns a dict of standardized metrics plus a special key '_report_end_date'
    indicating the consolidated annual 10-K end date used (if found).
    """
    url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
    headers = get_headers()

    try:
        r = requests.get(url, headers=headers, timeout=30)
        r.raise_for_status()
        company_facts = r.json()
    except Exception:
        return {}

    us_gaap = company_facts.get("facts", {}).get("us-gaap", {})
    dei = company_facts.get("facts", {}).get("dei", {})

    TAG_MAP = {
        "Assets": ["Assets"],
        "CurrentAssets": ["AssetsCurrent"],
        "Cash": ["CashAndCashEquivalentsAtCarryingValue", "Cash", "CashCashEquivalentsAndShortTermInvestments"],
        "ShortTermInvestments": ["MarketableSecuritiesCurrent", "ShortTermInvestments", "AvailableForSaleSecuritiesCurrent"],
        "AccountsReceivable": ["AccountsReceivableNetCurrent", "AccountsReceivableNet"],
        "Inventory": ["InventoryNet", "Inventory"],
        "PrepaidExpenses": ["PrepaidExpenseAndOtherAssetsCurrent", "PrepaidExpenses"],
        "OtherCurrentAssets": ["OtherAssetsCurrent"],
        "PropertyPlantEquipment": ["PropertyPlantAndEquipmentNet"],
        "PropertyPlantEquipmentGross": ["PropertyPlantAndEquipmentGross"],
        "AccumulatedDepreciationPPE": ["AccumulatedDepreciationDepletionAndAmortizationPropertyPlantAndEquipment"],
        "Goodwill": ["Goodwill"],
        "IntangibleAssets": ["IntangibleAssetsNetExcludingGoodwill", "FiniteLivedIntangibleAssetsNet"],
        "LongTermInvestments": ["LongTermInvestments", "MarketableSecuritiesNoncurrent", "AvailableForSaleSecuritiesNoncurrent"],
        "DeferredTaxAssetsNoncurrent": ["DeferredTaxAssetsNetNoncurrent"],
        "OtherNoncurrentAssets": ["OtherAssetsNoncurrent"],
        "RestrictedCash": ["RestrictedCashAndCashEquivalentsNoncurrent", "RestrictedCash"],
        "EquityMethodInvestments": ["EquityMethodInvestments"],
        "Liabilities": ["Liabilities"],
        "CurrentLiabilities": ["LiabilitiesCurrent"],
        "AccountsPayable": ["AccountsPayableCurrent", "AccountsPayable"],
        "AccruedLiabilities": ["AccruedLiabilitiesCurrent", "AccruedLiabilitiesAndOtherLiabilities"],
        "AccruedCompensation": ["EmployeeRelatedLiabilitiesCurrent"],
        "ShortTermDebt": ["ShortTermBorrowings", "CommercialPaper", "DebtCurrent", "ShortTermDebt"],
        "CurrentPortionLongTermDebt": ["LongTermDebtCurrent"],
        "LongTermDebt": ["LongTermDebtNoncurrent", "LongTermDebt", "LongTermDebtAndCapitalLeaseObligations"],
        "DeferredRevenue": ["DeferredRevenue", "ContractWithCustomerLiability", "DeferredRevenueNoncurrent", "ContractWithCustomerLiabilityCurrent"],
        "DeferredTaxLiabilities": ["DeferredTaxLiabilitiesNoncurrent", "DeferredTaxLiabilities"],
        "PensionLiabilities": ["PensionAndOtherPostretirementDefinedBenefitPlansLiabilitiesNoncurrent"],
        "OtherNoncurrentLiabilities": ["OtherLiabilitiesNoncurrent"],
        "OperatingLeaseLiability": ["OperatingLeaseLiabilityNoncurrent", "OperatingLeaseLiability"],
        "FinanceLeaseLiability": ["FinanceLeaseLiabilityNoncurrent", "FinanceLeaseLiability"],
        "StockholdersEquity": ["StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"],
        "CommonStock": ["CommonStockValue"],
        "PreferredStock": ["PreferredStockValue"],
        "AdditionalPaidInCapital": ["AdditionalPaidInCapitalCommonStock", "AdditionalPaidInCapital"],
        "RetainedEarnings": ["RetainedEarningsAccumulatedDeficit"],
        "TreasuryStock": ["TreasuryStockValue"],
        "AccumulatedOCI": ["AccumulatedOtherComprehensiveIncomeLossNetOfTax"],
        "NoncontrollingInterest": ["MinorityInterest", "NoncontrollingInterest"],
        "Revenue": ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet", "RevenueFromContractWithCustomerIncludingAssessedTax"],
        "CostOfRevenue": ["CostOfGoodsAndServicesSold", "CostOfRevenue", "CostOfGoodsSold"],
        "GrossProfit": ["GrossProfit"],
        "OperatingExpenses": ["OperatingExpenses"],
        "ResearchDevelopment": ["ResearchAndDevelopmentExpense"],
        "SellingGeneralAdmin": ["SellingGeneralAndAdministrativeExpense"],
        "MarketingExpense": ["SellingAndMarketingExpense"],
        "GeneralAdminExpense": ["GeneralAndAdministrativeExpense"],
        "RestructuringCharges": ["RestructuringCharges"],
        "ImpairmentCharges": ["AssetImpairmentCharges"],
        "OperatingIncome": ["OperatingIncomeLoss"],
        "InterestExpense": ["InterestExpense", "InterestExpenseDebt"],
        "InterestIncome": ["InterestIncomeOther", "InvestmentIncomeInterest", "InterestAndOtherIncome"],
        "OtherIncome": ["OtherNonoperatingIncomeExpense", "NonoperatingIncomeExpense"],
        "GainLossOnInvestments": ["GainLossOnInvestments"],
        "PreTaxIncome": ["IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest", "IncomeLossFromContinuingOperationsBeforeIncomeTaxes"],
        "TaxExpense": ["IncomeTaxExpenseBenefit"],
        "EffectiveTaxRate": ["EffectiveIncomeTaxRateContinuingOperations"],
        "NetIncome": ["NetIncomeLoss", "ProfitLoss"],
        "NetIncomeAvailableToCommon": ["NetIncomeLossAvailableToCommonStockholdersBasic"],
        "EPS": ["EarningsPerShareDiluted"],
        "EPSBasic": ["EarningsPerShareBasic"],
        "SharesOutstanding": ["CommonStockSharesOutstanding", "CommonStockSharesIssued"],
        "SharesOutstandingDiluted": ["WeightedAverageNumberOfDilutedSharesOutstanding"],
        "SharesOutstandingBasic": ["WeightedAverageNumberOfSharesOutstandingBasic"],
        "ComprehensiveIncome": ["ComprehensiveIncomeNetOfTax"],
        "OperatingCashFlow": ["NetCashProvidedByUsedInOperatingActivities"],
        "CapitalExpenditures": ["PaymentsToAcquirePropertyPlantAndEquipment"],
        "InvestingCashFlow": ["NetCashProvidedByUsedInInvestingActivities"],
        "FinancingCashFlow": ["NetCashProvidedByUsedInFinancingActivities"],
        "DividendsPaid": ["PaymentsOfDividends", "PaymentsOfDividendsCommonStock"],
        "StockRepurchase": ["PaymentsForRepurchaseOfCommonStock"],
        "DebtIssuance": ["ProceedsFromIssuanceOfLongTermDebt"],
        "DebtRepayment": ["RepaymentsOfLongTermDebt"],
        "DepreciationAmortization": ["DepreciationDepletionAndAmortization", "Depreciation"],
        "Amortization": ["AmortizationOfIntangibleAssets"],
        "StockBasedComp": ["ShareBasedCompensation", "AllocatedShareBasedCompensationExpense"],
        "ChangeInWorkingCapital": ["IncreaseDecreaseInOperatingCapital"],
        "ChangeInAR": ["IncreaseDecreaseInAccountsReceivable"],
        "ChangeInInventory": ["IncreaseDecreaseInInventories"],
        "ChangeInAP": ["IncreaseDecreaseInAccountsPayable"],
        "ChangeInAccruedLiabilities": ["IncreaseDecreaseInAccruedLiabilities"],
        "DeferredIncomeTaxes": ["DeferredIncomeTaxExpenseBenefit"],
        "ProceedsFromStockIssuance": ["ProceedsFromIssuanceOfCommonStock"],
        "AcquisitionsCash": ["PaymentsToAcquireBusinessesNetOfCashAcquired"],
        "ProceedsFromAssetSales": ["ProceedsFromSaleOfPropertyPlantAndEquipment"],
        "PurchaseOfInvestments": ["PaymentsToAcquireInvestments", "PaymentsToAcquireAvailableForSaleSecuritiesDebt"],
        "SaleOfInvestments": ["ProceedsFromSaleOfAvailableForSaleSecuritiesDebt", "ProceedsFromSaleOfAvailableForSaleSecurities"],
        "InterestIncomeBank": ["InterestAndDividendIncomeOperating", "InterestIncomeOperating"],
        "InterestExpenseBank": ["InterestExpenseDeposits"],
        "NetInterestIncome": ["InterestIncomeExpenseAfterProvisionForLoanLoss", "InterestIncomeExpenseNet"],
        "ProvisionLoanLosses": ["ProvisionForLoanLossesExpensed", "ProvisionForLoanLeaseAndOtherLosses"],
        "NonInterestIncome": ["NoninterestIncome"],
        "Loans": ["LoansAndLeasesReceivableNetOfDeferredIncome", "LoansAndLeasesReceivableNetReportedAmount"],
        "LoansGross": ["LoansAndLeasesReceivableGrossCarryingAmount"],
        "Deposits": ["Deposits"],
        "AllowanceLoanLosses": ["FinancingReceivableAllowanceForCreditLosses"],
        "TradingAssets": ["TradingSecurities"],
        "SecuritiesAvailableForSale": ["AvailableForSaleSecuritiesDebtSecurities"],
        "FederalFundsSold": ["FederalFundsSoldAndSecuritiesPurchasedUnderAgreementsToResell"],
        "NonPerformingLoans": ["FinancingReceivableNonaccrualNoAllowance"],
        "RealEstateInvestments": ["RealEstateInvestmentPropertyNet"],
        "RealEstateAtCost": ["RealEstateInvestmentPropertyAtCost"],
        "AccumulatedDepreciationRE": ["RealEstateInvestmentPropertyAccumulatedDepreciation"],
        "RentalIncome": ["OperatingLeaseLeaseIncome"],
        "PropertyOperatingExpense": ["DirectCostsOfLeasedAndRentedPropertyOrEquipment"],
        "FFO": ["FundsFromOperations"],
        "AFFO": ["AdjustedFundsFromOperations"],
        "NOI": ["NetOperatingIncome"],
        "RealEstateAcquisitions": ["PaymentsToAcquireRealEstate"],
        "RealEstateDispositions": ["ProceedsFromSaleOfRealEstateHeldforinvestment"],
        "NumberOfProperties": ["NumberOfRealEstateProperties"],
        "SquareFootage": ["AreaOfRealEstateProperty"],
        "PremiumsEarned": ["PremiumsEarnedNet"],
        "PremiumsWritten": ["PremiumsWrittenNet"],
        "LossesClaims": ["LiabilityForClaimsAndClaimsAdjustmentExpense"],
        "PolicyholderBenefits": ["PolicyholderBenefitsAndClaimsIncurredNet"],
        "InvestmentIncomeInsurance": ["NetInvestmentIncome"],
        "LossRatio": ["PropertyCasualtyInsuranceLossRatio"],
        "ExpenseRatio": ["PropertyCasualtyInsuranceExpenseRatio"],
        "CombinedRatio": ["PropertyCasualtyInsuranceCombinedRatio"],
        "ReinsuranceRecoverables": ["ReinsuranceRecoverablesOnPaidAndUnpaidLosses"],
        "RegulatedRevenue": ["RegulatedOperatingRevenue"],
        "RegulatoryAssets": ["RegulatoryAssets"],
        "RegulatoryLiabilities": ["RegulatoryLiabilities"],
        "ProvedReserves": ["ProvedDevelopedAndUndevelopedReserves"],
        "ExplorationExpense": ["ExplorationExpense"],
    }

    BALANCE_SHEET_ITEMS = {
        "Assets", "CurrentAssets", "Cash", "ShortTermInvestments", "AccountsReceivable",
        "Inventory", "PrepaidExpenses", "OtherCurrentAssets", "PropertyPlantEquipment",
        "PropertyPlantEquipmentGross", "AccumulatedDepreciationPPE", "Goodwill", "IntangibleAssets",
        "LongTermInvestments", "DeferredTaxAssetsNoncurrent", "OtherNoncurrentAssets",
        "RestrictedCash", "EquityMethodInvestments", "Liabilities", "CurrentLiabilities",
        "AccountsPayable", "AccruedLiabilities", "AccruedCompensation", "ShortTermDebt",
        "CurrentPortionLongTermDebt", "LongTermDebt", "DeferredRevenue", "DeferredTaxLiabilities",
        "PensionLiabilities", "OtherNoncurrentLiabilities", "OperatingLeaseLiability",
        "FinanceLeaseLiability", "StockholdersEquity", "CommonStock", "PreferredStock",
        "AdditionalPaidInCapital", "RetainedEarnings", "TreasuryStock", "AccumulatedOCI",
        "NoncontrollingInterest", "SharesOutstanding", "Loans", "LoansGross", "Deposits",
        "AllowanceLoanLosses", "TradingAssets", "SecuritiesAvailableForSale", "FederalFundsSold",
        "NonPerformingLoans", "RealEstateInvestments", "RealEstateAtCost", "AccumulatedDepreciationRE",
        "NumberOfProperties", "SquareFootage", "LossesClaims", "ReinsuranceRecoverables",
        "RegulatoryAssets", "RegulatoryLiabilities", "ProvedReserves"
    }

    def get_latest_annual_fact(concept_data, is_instant=False):
        units = concept_data.get("units", {})

        # Prioritize USD, shares, pure, USD/shares (typical SEC units)
        for unit_type in ["USD", "shares", "pure", "USD/shares"]:
            if unit_type not in units:
                continue

            facts = units[unit_type]

            # Keep only 10-K / 10-K/A when available
            valid_facts = [f for f in facts if f.get("form") in ["10-K", "10-K/A"]]
            if not valid_facts:
                valid_facts = facts

            # For flows (not instant), filter for ~annual period length (close to 365 days)
            if not is_instant:
                annual_facts = []
                for f in valid_facts:
                    start = f.get("start")
                    end = f.get("end")
                    if start and end:
                        try:
                            start_dt = datetime.strptime(start, "%Y-%m-%d")
                            end_dt = datetime.strptime(end, "%Y-%m-%d")
                            days = (end_dt - start_dt).days
                            if 350 <= days <= 380:
                                annual_facts.append(f)
                        except:
                            pass

                if annual_facts:
                    valid_facts = annual_facts

            if valid_facts:
                # sort most recent by end date
                sorted_facts = sorted(valid_facts, key=lambda x: x.get("end", ""), reverse=True)
                if sorted_facts:
                    return sorted_facts[0].get("val"), sorted_facts[0].get("end")

        return None, None

    data = {}
    target_end_date = None

    # First, try to determine a consolidated 10-K annual end date from Revenue or other primary flow items.
    for tags in [["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet"]]:
        for tag in tags:
            if tag in us_gaap:
                units = us_gaap[tag].get("units", {})
                if "USD" in units:
                    facts = units["USD"]
                    annual_facts = []
                    for f in facts:
                        if f.get("form") in ["10-K", "10-K/A"]:
                            start = f.get("start")
                            end = f.get("end")
                            if start and end:
                                try:
                                    start_dt = datetime.strptime(start, "%Y-%m-%d")
                                    end_dt = datetime.strptime(end, "%Y-%m-%d")
                                    days = (end_dt - start_dt).days
                                    if 350 <= days <= 380:
                                        annual_facts.append(f)
                                except:
                                    pass
                    if annual_facts:
                        latest = sorted(annual_facts, key=lambda x: x.get("end", ""), reverse=True)[0]
                        target_end_date = latest.get("end")
                        data["Revenue"] = latest.get("val")
                        break
        if target_end_date:
            break

    def get_fact_for_period(concept_data, target_date, is_instant=False):
        units = concept_data.get("units", {})

        for unit_type in ["USD", "shares", "pure", "USD/shares"]:
            if unit_type not in units:
                continue

            facts = units[unit_type]

            if is_instant:
                matching = [f for f in facts if f.get("end") == target_date and f.get("form") in ["10-K", "10-K/A"]]
                if not matching:
                    matching = [f for f in facts if f.get("end") == target_date]
                if matching:
                    return matching[-1].get("val")
            else:
                for f in facts:
                    if f.get("end") == target_date and f.get("form") in ["10-K", "10-K/A"]:
                        start = f.get("start")
                        end = f.get("end")
                        if start and end:
                            try:
                                start_dt = datetime.strptime(start, "%Y-%m-%d")
                                end_dt = datetime.strptime(end, "%Y-%m-%d")
                                days = (end_dt - start_dt).days
                                if 350 <= days <= 380:
                                    return f.get("val")
                            except:
                                pass

                matching = [f for f in facts if f.get("end") == target_date]
                if matching:
                    for f in matching:
                        start = f.get("start")
                        end = f.get("end")
                        if start and end:
                            try:
                                start_dt = datetime.strptime(start, "%Y-%m-%d")
                                end_dt = datetime.strptime(end, "%Y-%m-%d")
                                days = (end_dt - start_dt).days
                                if 350 <= days <= 380:
                                    return f.get("val")
                            except:
                                pass

        return None

    # For each metric, attempt to get value for target_end_date (10-K consolidated) if we determined it,
    # otherwise fall back to latest annual fact.
    for metric, tags in TAG_MAP.items():
        if metric == "Revenue" and data.get("Revenue"):
            continue

        is_instant = metric in BALANCE_SHEET_ITEMS

        for tag in tags:
            concept = us_gaap.get(tag) or dei.get(tag)
            if concept:
                if target_end_date:
                    val = get_fact_for_period(concept, target_end_date, is_instant)
                    if val is not None:
                        data[metric] = val
                        break
                else:
                    val, end_date = get_latest_annual_fact(concept, is_instant)
                    if val is not None:
                        data[metric] = val
                        # set target end date if not already set
                        if not target_end_date and end_date:
                            target_end_date = end_date
                        break

    # simple derived metrics
    if not data.get("GrossProfit") and data.get("Revenue") and data.get("CostOfRevenue"):
        try:
            data["GrossProfit"] = data["Revenue"] - data["CostOfRevenue"]
        except:
            pass

    if not data.get("OperatingIncome") and data.get("GrossProfit"):
        opex = (data.get("ResearchDevelopment") or 0) + (data.get("SellingGeneralAdmin") or 0)
        if opex > 0:
            try:
                data["OperatingIncome"] = data["GrossProfit"] - opex
            except:
                pass

    # Attach the consolidated annual end date used (if any) for provenance checks
    if target_end_date:
        data["_report_end_date"] = target_end_date

    return data


def standardize_raw_data(raw):
    """
    Ensure canonical keys exist (aliases mapped), cast numeric-like strings to numbers where possible,
    and return a copy with standardized names. This reduces schema inconsistencies.
    """
    if not isinstance(raw, dict):
        return raw
    data = dict(raw)  # shallow copy

    # schema alias map: alternate names => canonical name expected elsewhere
    aliases = {
        "minorityInterest": "NoncontrollingInterest",
        "minority_interest": "NoncontrollingInterest",
        "restrictedCash": "RestrictedCash",
        "restricted_cash": "RestrictedCash",
        "prepaid_expenses": "PrepaidExpenses",
        "intangible_assets": "IntangibleAssets",
        "goodwill": "Goodwill",
        "deferred_revenue_current": "DeferredRevenue",
        "deferred_revenue": "DeferredRevenue",
        "deferred_tax_liabilities": "DeferredTaxLiabilities",
        "deferred_tax_liabilities_noncurrent": "DeferredTaxLiabilities",
        "shares_outstanding": "SharesOutstanding",
        "shares_outstanding_basic": "SharesOutstandingBasic",
        "shares_outstanding_diluted": "SharesOutstandingDiluted",
        "net_income": "NetIncome",
        "net_income_available_to_common": "NetIncomeAvailableToCommon",
    }

    for alt, canon in aliases.items():
        if alt in data and canon not in data:
            data[canon] = data.get(alt)

    # Coerce numeric-like values (strings) to numbers where feasible
    for k, v in list(data.items()):
        if isinstance(v, str):
            v_str = v.strip().replace(',', '')
            try:
                if v_str.startswith('(') and v_str.endswith(')'):
                    num = -float(v_str.strip('()'))
                    data[k] = num
                else:
                    if '.' in v_str:
                        data[k] = float(v_str)
                    else:
                        if v_str.isdigit():
                            data[k] = int(v_str)
            except:
                pass

    return data


def flag_one_offs(raw_data):
    """
    Detect obvious one-off items that might distort metrics.
    Heuristics:
    - Large Gain/Loss on Investments relative to NetIncome
    - Large Restructuring charges relative to OperatingIncome or Revenue
    - Large asset sales (ProceedsFromAssetSales) relative to Revenue/NetIncome
    Returns list of flags (strings).
    """
    flags = []
    try:
        ni = raw_data.get('NetIncome') or 0
        oi = raw_data.get('OperatingIncome') or 0
        rev = raw_data.get('Revenue') or 0

        gain_loss = raw_data.get('GainLossOnInvestments') or 0
        if ni and abs(gain_loss) > abs(ni) * 0.2 and abs(gain_loss) > 1e6:
            flags.append(f"Large Gain/Loss on Investments ({gain_loss}) relative to Net Income ({ni})")

        restructuring = raw_data.get('RestructuringCharges') or 0
        if oi and restructuring > abs(oi) * 1.0 and restructuring > 1e6:
            flags.append(f"Large Restructuring Charges ({restructuring}) relative to Operating Income ({oi})")
        elif rev and restructuring > rev * 0.05 and restructuring > 1e6:
            flags.append(f"Significant restructuring charges ({restructuring}) relative to Revenue ({rev})")

        proceeds = raw_data.get('ProceedsFromAssetSales') or 0
        if rev and abs(proceeds) > rev * 0.05 and abs(proceeds) > 1e6:
            flags.append(f"Material proceeds from asset sales ({proceeds}) relative to Revenue ({rev})")

        tax_benefit = raw_data.get('TaxExpense')
        if tax_benefit and ni and abs(tax_benefit) > abs(ni) * 0.5:
            flags.append("Unusually large tax expense/benefit relative to net income")

    except Exception:
        pass

    return flags


def validate_fundamentals(data):
    issues = []

    revenue = data.get("Revenue")
    gross_profit = data.get("GrossProfit")
    operating_income = data.get("OperatingIncome")
    net_income = data.get("NetIncome")

    # Basic sanity checks
    if revenue and gross_profit:
        try:
            if gross_profit > revenue * 1.05:
                issues.append(f"Gross Profit ({gross_profit:,.0f}) > Revenue ({revenue:,.0f})")
        except:
            pass

    if revenue and operating_income:
        try:
            if operating_income > revenue * 1.05:
                issues.append(f"Operating Income ({operating_income:,.0f}) > Revenue ({revenue:,.0f})")
        except:
            pass

    if revenue and net_income:
        try:
            if net_income > revenue * 1.05:
                issues.append(f"Net Income ({net_income:,.0f}) > Revenue ({revenue:,.0f})")
        except:
            pass

    # Required fields presence
    required = ["Revenue", "NetIncome", "Assets", "SharesOutstanding"]
    missing = [f for f in required if data.get(f) is None]
    if missing:
        issues.append(f"Missing critical items: {', '.join(missing)}")

    # Data mixing detection: ensure that the data appears to be consolidated annual snapshot
    if "_report_end_date" not in data:
        issues.append("No consolidated annual 10-K end date detected; possible mixed-period data")

    return issues


def calculate_ratios(raw_data, industry):
    ratios = {}

    try:
        # Recompute total debt from components to ensure consistency
        total_debt = (raw_data.get('LongTermDebt') or 0) + (raw_data.get('ShortTermDebt') or 0) + (raw_data.get('CurrentPortionLongTermDebt') or 0)
        if total_debt > 0:
            ratios['Total_Debt'] = total_debt
            raw_data['_meta_total_debt_recalculated'] = True

        ebitda = None
        if raw_data.get('OperatingIncome') and raw_data.get('DepreciationAmortization'):
            ebitda = raw_data['OperatingIncome'] + raw_data['DepreciationAmortization']
        elif raw_data.get('OperatingIncome'):
            ebitda = raw_data['OperatingIncome'] + (raw_data.get('Amortization') or 0)
        if ebitda:
            ratios['EBITDA'] = ebitda

        if raw_data.get('OperatingIncome'):
            ratios['EBIT'] = raw_data['OperatingIncome']

        revenue = raw_data.get('Revenue')
        if revenue and revenue > 0:
            if raw_data.get('GrossProfit') is not None:
                gp = raw_data['GrossProfit']
                if gp <= revenue:
                    ratios['Gross_Margin'] = round((gp / revenue) * 100, 2)

            if raw_data.get('OperatingIncome') is not None:
                oi = raw_data['OperatingIncome']
                if oi <= revenue:
                    ratios['Operating_Margin'] = round((oi / revenue) * 100, 2)

            if raw_data.get('NetIncome') is not None:
                ni = raw_data['NetIncome']
                if abs(ni) <= revenue * 2:
                    ratios['Net_Margin'] = round((ni / revenue) * 100, 2)

            if ebitda is not None and ebitda <= revenue * 1.5:
                ratios['EBITDA_Margin'] = round((ebitda / revenue) * 100, 2)

            if raw_data.get('PreTaxIncome') is not None:
                pti = raw_data['PreTaxIncome']
                if abs(pti) <= revenue * 2:
                    ratios['Pretax_Margin'] = round((pti / revenue) * 100, 2)

        shares = raw_data.get('SharesOutstanding') or raw_data.get('SharesOutstandingBasic') or raw_data.get('SharesOutstandingDiluted')
        if shares and shares > 0:
            raw_data['_shares'] = shares

            # EPS uses NetIncomeAvailableToCommon when present, otherwise NetIncome
            numerator = raw_data.get('NetIncomeAvailableToCommon') if raw_data.get('NetIncomeAvailableToCommon') is not None else raw_data.get('NetIncome')
            if numerator is not None:
                try:
                    eps_val = numerator / shares
                    ratios['EPS_Calculated'] = round(eps_val, 5)
                except:
                    ratios['EPS_Calculated'] = None

            if raw_data.get('StockholdersEquity') is not None:
                try:
                    ratios['Book_Value_Per_Share'] = raw_data['StockholdersEquity'] / shares
                except:
                    ratios['Book_Value_Per_Share'] = None

            if revenue is not None:
                try:
                    ratios['Revenue_Per_Share'] = revenue / shares
                except:
                    ratios['Revenue_Per_Share'] = None

            if raw_data.get('OperatingCashFlow') is not None:
                try:
                    ratios['Cash_Flow_Per_Share'] = raw_data['OperatingCashFlow'] / shares
                except:
                    ratios['Cash_Flow_Per_Share'] = None

        if raw_data.get('NetIncome') is not None:
            ni = raw_data['NetIncome']
            if raw_data.get('StockholdersEquity') and raw_data['StockholdersEquity'] > 0:
                roe = (ni / raw_data['StockholdersEquity']) * 100
                if -200 < roe < 200:
                    ratios['ROE'] = round(roe, 2)

            if raw_data.get('Assets') and raw_data['Assets'] > 0:
                roa = (ni / raw_data['Assets']) * 100
                if -100 < roa < 100:
                    ratios['ROA'] = round(roa, 2)

        if total_debt > 0:
            if raw_data.get('StockholdersEquity') and raw_data['StockholdersEquity'] > 0:
                ratios['Debt_to_Equity'] = total_debt / raw_data['StockholdersEquity']

            if ebitda and ebitda > 0:
                ratios['Debt_to_EBITDA'] = total_debt / ebitda

            if raw_data.get('Assets') and raw_data['Assets'] > 0:
                ratios['Debt_to_Assets'] = total_debt / raw_data['Assets']

        # Interest coverage with clearer handling
        if raw_data.get('OperatingIncome') is not None:
            # prefer bank-specific tags if present
            ie = raw_data.get('InterestExpense')
            if ie is None and raw_data.get('InterestExpenseBank') is not None:
                ie = raw_data.get('InterestExpenseBank')
            if ie is None:
                ratios['Interest_Coverage'] = None
                ratios['Interest_Coverage_Note'] = "Interest expense missing; coverage undefined"
            else:
                try:
                    ie_val = ie or 0
                    if ie_val > 0:
                        ratios['Interest_Coverage'] = raw_data['OperatingIncome'] / ie_val
                    else:
                        ratios['Interest_Coverage'] = None
                        ratios['Interest_Coverage_Note'] = "Interest expense is zero; coverage undefined"
                except:
                    ratios['Interest_Coverage'] = None
                    ratios['Interest_Coverage_Note'] = "Error computing interest coverage"

        # Liquidity ratios
        if raw_data.get('CurrentAssets') and raw_data.get('CurrentLiabilities') and raw_data['CurrentLiabilities'] > 0:
            try:
                ratios['Current_Ratio'] = raw_data['CurrentAssets'] / raw_data['CurrentLiabilities']
            except:
                ratios['Current_Ratio'] = None

            quick_assets = (raw_data.get('Cash') or 0) + (raw_data.get('ShortTermInvestments') or 0) + (raw_data.get('AccountsReceivable') or 0)
            try:
                ratios['Quick_Ratio'] = quick_assets / raw_data['CurrentLiabilities']
            except:
                ratios['Quick_Ratio'] = None

        if raw_data.get('Cash') and raw_data.get('CurrentLiabilities') and raw_data['CurrentLiabilities'] > 0:
            try:
                ratios['Cash_Ratio'] = raw_data['Cash'] / raw_data['CurrentLiabilities']
            except:
                ratios['Cash_Ratio'] = None

        if raw_data.get('CurrentAssets') is not None and raw_data.get('CurrentLiabilities') is not None:
            ratios['Working_Capital'] = raw_data['CurrentAssets'] - raw_data['CurrentLiabilities']

        # Efficiency ratios (receivables/inventory/payables)
        if revenue and revenue > 0:
            if raw_data.get('Assets') and raw_data['Assets'] > 0:
                ratios['Asset_Turnover'] = revenue / raw_data['Assets']

            if raw_data.get('AccountsReceivable') and raw_data['AccountsReceivable'] > 0:
                try:
                    ratios['Receivables_Turnover'] = revenue / raw_data['AccountsReceivable']
                    dso = 365 / ratios['Receivables_Turnover']
                    ratios['Days_Sales_Outstanding'] = round(dso, 5)
                except:
                    pass

            cogs = raw_data.get('CostOfRevenue')
            if cogs and cogs > 0:
                if raw_data.get('Inventory') and raw_data['Inventory'] > 0:
                    try:
                        ratios['Inventory_Turnover'] = cogs / raw_data['Inventory']
                        dio = 365 / ratios['Inventory_Turnover']
                        ratios['Days_Inventory_Outstanding'] = round(dio, 3)
                    except:
                        pass

                if raw_data.get('AccountsPayable') and raw_data['AccountsPayable'] > 0:
                    try:
                        ratios['Payables_Turnover'] = cogs / raw_data['AccountsPayable']
                        dpo = 365 / ratios['Payables_Turnover']
                        ratios['Days_Payable_Outstanding'] = round(dpo, 4)
                    except:
                        pass

        if ratios.get('Days_Sales_Outstanding') is not None and ratios.get('Days_Inventory_Outstanding') is not None and ratios.get('Days_Payable_Outstanding') is not None:
            try:
                dso_val = ratios['Days_Sales_Outstanding']
                dio_val = ratios['Days_Inventory_Outstanding']
                dpo_val = ratios['Days_Payable_Outstanding']
                ccc = dio_val + dso_val - dpo_val
                ratios['Cash_Conversion_Cycle'] = round(ccc, 5)
            except:
                pass

        # Free cash flow
        if raw_data.get('OperatingCashFlow') is not None and raw_data.get('CapitalExpenditures') is not None:
            try:
                fcf = raw_data['OperatingCashFlow'] - abs(raw_data['CapitalExpenditures'])
                ratios['Free_Cash_Flow'] = fcf
            except:
                pass

    except Exception:
        pass

    return ratios


def fetch_market_data(ticker):
    """
    Fetch market data (share price, market cap).
    Strategy:
    1) Try YahooFinance v10 quoteSummary (best-effort)
    2) If missing or incomplete, try Nasdaq public summary endpoint as a fallback for share price/market cap
    Notes:
    - We do not require these fields for SEC-only fundamentals, but try to populate when available.
    """
    res = {
        "share_price": None,
        "market_cap": None,
        "currency": None,
        "source": None,
        "fetched_at": None
    }

    headers = {"User-Agent": "Andres Garcia andres@realemail.com", "Accept": "application/json"}

    # 1) YahooFinance attempt
    try:
        url = f"https://query1.finance.yahoo.com/v10/finance/quoteSummary/{ticker}?modules=price"
        r = requests.get(url, headers=headers, timeout=10)
        r.raise_for_status()
        j = r.json()
        price = j.get("quoteSummary", {}).get("result", [{}])[0].get("price", {})
        if price:
            if "regularMarketPrice" in price and price["regularMarketPrice"] and "raw" in price["regularMarketPrice"]:
                res["share_price"] = price["regularMarketPrice"]["raw"]
            if "marketCap" in price and price["marketCap"] and "raw" in price["marketCap"]:
                res["market_cap"] = price["marketCap"]["raw"]
            if "currency" in price:
                res["currency"] = price.get("currency")
            res["source"] = "YahooFinance"
            res["fetched_at"] = datetime.utcnow().isoformat() + "Z"
            if res["share_price"] is not None or res["market_cap"] is not None:
                return res
    except Exception:
        pass

    # 2) Nasdaq public summary endpoint fallback (best-effort)
    try:
        nasdaq_url = f"https://api.nasdaq.com/api/quote/{ticker}/summary?assetclass=stocks"
        nas_headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json, text/plain, */*"}
        r = requests.get(nasdaq_url, headers=nas_headers, timeout=10)
        r.raise_for_status()
        j = r.json()
        data = j.get("data", {}) or {}
        summary = data.get("summaryData", {}) or {}
        mc = None
        mc_field = summary.get("MarketCap", {}) or {}
        mc_val = mc_field.get("value") if mc_field else None
        if mc_val:
            mc_val_clean = mc_val.replace('$', '').replace(',', '').strip()
            try:
                mc = int(mc_val_clean)
            except:
                try:
                    mc = float(mc_val_clean)
                except:
                    mc = None
        prev_close_field = summary.get("PreviousClose", {}) or {}
        prev_close = prev_close_field.get("value") if prev_close_field else None
        share_price = None
        if prev_close and prev_close != "N/A":
            pc_clean = re.sub(r'[^\d\.\-]', '', prev_close)
            try:
                share_price = float(pc_clean)
            except:
                share_price = None

        if mc is not None or share_price is not None:
            res["share_price"] = share_price
            res["market_cap"] = mc
            res["currency"] = "USD"
            res["source"] = "NasdaqSummary"
            res["fetched_at"] = datetime.utcnow().isoformat() + "Z"
            return res
    except Exception:
        pass

    return res


def get_occupancy_rate(ticker):
    ticker = ticker.upper().strip()
    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
                      '(KHTML, like Gecko) Chrome/130.0 Safari/537.36 your.real.email@gmail.com',
    }

    try:
        data = requests.get("https://www.sec.gov/files/company_tickers.json", headers=headers, timeout=15).json()
        cik = next((str(v['cik_str']).zfill(10) for v in data.values() if v['ticker'].upper() == ticker), None)
        if not cik:
            return {"error": "Ticker not found", "ticker": ticker}
    except:
        return {"error": "SEC blocked request — use real email in User-Agent", "ticker": ticker}

    try:
        filings = requests.get(f"https://data.sec.gov/submissions/CIK{cik}.json", headers=headers).json()
    except:
        return {"error": "Failed to fetch filings", "ticker": ticker}

    forms = filings['filings']['recent']['form']
    accs = filings['filings']['recent']['accessionNumber']
    docs = filings['filings']['recent']['primaryDocument']
    filing_urls = []
    for i, form in enumerate(forms):
        if form in ('10-Q', '10-K'):
            acc = accs[i].replace('-', '')
            url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc}/{docs[i]}"
            filing_urls.append((form, url))
            if len(filing_urls) >= 3:
                break

    if not filing_urls:
        return {"error": "No recent filings found", "ticker": ticker}

    for form_type, url in filing_urls:
        try:
            html = requests.get(url, headers=headers, timeout=20).text
        except:
            continue
        soup = BeautifulSoup(html, 'html5lib')

        for tag in soup.find_all(['ix:nonfraction', 'ix:nonFraction']):
            context = tag.get('contextref', '')
            if 'current' not in context.lower() and 'asof' not in context.lower():
                continue
            gp_text = tag.parent.parent.get_text() if tag.parent and tag.parent.parent else ''
            parent_text = (gp_text + ' ' + (tag.parent.get_text() if tag.parent else '')).strip()
            if any(kw in parent_text.lower() for kw in ['occupancy', 'leased', 'percent leased', 'portfolio', 'properties leased']):
                num = tag.get_text(strip=True).replace(',', '')
                if re.match(r'^\d+\.?\d*$', num):
                    perc = float(num)
                    if 50 <= perc <= 100:
                        return {
                            "ticker": ticker,
                            "occupancy_rate": round(perc, 2),
                            "source": f"XBRL ({form_type})",
                            "context": parent_text,
                            "filing_url": url
                        }

        text = soup.get_text(separator=' ')
        text = re.sub(r'\s+', ' ', text)
        text = re.sub(r'(\d+)\s*\.\s*(\d+)\s*(%)', r'\1.\2\3', text)
        text = re.sub(r'(\d+)\s*\.\s*(\d+)', r'\1.\2', text)

        table_pattern = r'(?:percent|percentage)\s+leased.*?(\d+\.?\d*)\s*(%|percent)'
        table_matches = re.findall(table_pattern, text, re.IGNORECASE)
        if table_matches:
            for tm in table_matches:
                perc_num = float(tm[0])
                if 90 <= perc_num <= 100:
                    return {
                        "ticker": ticker,
                        "occupancy_rate": round(perc_num, 1),
                        "source": f"TABLE ({form_type})",
                        "context": f"Percent leased: {perc_num:.1f}% (from portfolio summary)",
                        "filing_url": url
                    }

        patterns = [
            r'decreased\s+(?:approximately\s+)?\d+\.?\d*%\s+to\s+(\d+\.?\d*)%',
            r'increased\s+(?:approximately\s+)?\d+\.?\d*%\s+to\s+(\d+\.?\d*)%',
            r'percent\s+leased\s*(?:was|is|remained|stood)?\s*[:\-]?\s*(\d+\.?\d*)%',
            r'percentage\s+leased\s*(?:was|is|remained|stood)?\s*[:\-]?\s*(\d+\.?\d*)%',
            r'properties.*?leased.*?(\d+\.?\d*)%',
            r'leased\s*(?:was|is|stood)?\s*[:\-]?\s*(\d+\.?\d*)%',
            r'occupancy\s*(?:was|is|stood|remained)?\s*[:\-]?\s*(\d+\.?\d*)%',
            r'portfolio\s+(?:was|is)\s+(\d+\.?\d*)%\s+(?:leased|occupied)',
            r'(\d+\.?\d*)%\s+(?:leased|occupied)',
            r'(\d+\.?\d*)%\s+of\s+our\s+(?:properties|portfolio)',
            r'same\s*store[^.?!]{0,1000}(\d+\.?\d*)%',
        ]
        candidates = []
        for pattern in patterns:
            for m in re.finditer(pattern, text, re.IGNORECASE):
                perc = m.group(1)
                try:
                    perc_num = float(perc)
                except:
                    continue
                if not (50 <= perc_num <= 100):
                    continue
                start = max(0, m.start() - 1000)
                end = min(len(text), m.end() + 1000)
                context = text[start:end]
                sentences = re.split(r'[.?!]', context)
                sentence = sentences[0] + '.'
                for s in sentences[:3]:
                    if len(s) > 50 and any(kw in s.lower() for kw in ['occupancy', 'leased', 'portfolio']):
                        sentence = s + '.'
                        break
                sentence_lower = sentence.lower()
                if any(bad in sentence_lower for bad in [
                    'definition', 'means', 'defined as', 'earlier of', 'achieving',
                    'stabilization', 'threshold', 'minimum', 'target', 'expense', 'rent', 'cash basis'
                ]):
                    continue
                score = 0
                if 'same store' in sentence_lower: score += 10
                if 'portfolio' in sentence_lower: score += 5
                if 'as of' in sentence_lower or 'ended' in sentence_lower: score += 8
                if 'leased' in sentence_lower or 'occupancy' in sentence_lower: score += 5
                if 'decreased' in sentence_lower or 'increased' in sentence_lower: score += 3
                if 'percent leased' in sentence_lower: score += 7
                candidates.append((score, perc_num, sentence.strip()))
        if candidates:
            best = max(candidates, key=lambda x: (x[0], x[1]))
            return {
                "ticker": ticker,
                "occupancy_rate": round(best[1], 2),
                "source": f"TEXT ({form_type})",
                "context": best[2],
                "filing_url": url
            }

    return {"error": "No reliable rate found across recent filings", "ticker": ticker}


def fetch_comprehensive_fundamentals(ticker):
    """
    Main orchestration: get CIK, company info, XBRL fundamentals, standardize schema,
    validate, calculate ratios, fetch market data (best-effort), detect one-offs, and
    assemble a comprehensive result.

    Enhancements per user request:
    - Aggressively infer common small/missing fields (APIC, common stock, treasury, goodwill, intangibles)
      but add _meta_inferred_<field> flags so downstream can detect inferred values.
    - Recompute key aggregates (total_debt, free cash flow, OCF when possible) and set meta flags.
    - Recalculate ratios that depend on fixed items (book value per share, liquidity, leverage).
    - Use bank-specific interest tags when present.
    - Ensure no silent nulls break downstream calculations; annotate instead.
    """
    cik = get_cik(ticker)
    if not cik:
        return {"error": f"Ticker {ticker} not found"}

    company_info = get_company_info(cik)
    industry = detect_industry(company_info.get('sic'), company_info.get('sic_description'))

    raw_data = extract_xbrl_data_optimized(cik)
    raw_data = standardize_raw_data(raw_data)

    # Conservative fills & inferences (line-by-line careful handling)
    # Fields to infer/default to 0 when missing but mark with _meta_inferred_<field> = True
    infer_zero_fields = [
        # equity / small-balance items (user requested)
        'AdditionalPaidInCapital', 'CommonStock', 'TreasuryStock',
        'Goodwill', 'IntangibleAssets',
        # cashflow/investing items that are often zero
        'AcquisitionsCash', 'ProceedsFromAssetSales', 'ImpairmentCharges', 'Amortization',
        'RestructuringCharges', 'GainLossOnInvestments',
        # various small balances/expenses
        'DeferredTaxAssetsNoncurrent', 'InterestExpense', 'AccruedLiabilities',
    ]

    for f in infer_zero_fields:
        if raw_data.get(f) is None:
            raw_data[f] = 0
            raw_data[f'_meta_inferred_{f}'] = True

    # For banks prefer bank-specific tags if present and populate missing interest fields
    if raw_data.get('InterestExpense') is None and raw_data.get('InterestExpenseBank') is not None:
        raw_data['InterestExpense'] = raw_data.get('InterestExpenseBank')
        raw_data['_meta_inferred_InterestExpense_from_bank_tag'] = True
    if raw_data.get('InterestIncome') is None and raw_data.get('InterestIncomeBank') is not None:
        raw_data['InterestIncome'] = raw_data.get('InterestIncomeBank')
        raw_data['_meta_inferred_InterestIncome_from_bank_tag'] = True

    # Fill current assets / liabilities if missing and components are available
    try:
        if raw_data.get('CurrentAssets') is None:
            # try to sum likely current asset components if present
            ca_components = [
                raw_data.get('Cash') or 0,
                raw_data.get('ShortTermInvestments') or 0,
                raw_data.get('AccountsReceivable') or 0,
                raw_data.get('Inventory') or 0,
                raw_data.get('PrepaidExpenses') or 0,
                raw_data.get('OtherCurrentAssets') or 0
            ]
            if any(x != 0 for x in ca_components):
                raw_data['CurrentAssets'] = sum(ca_components)
                raw_data['_meta_inferred_CurrentAssets_from_components'] = True
    except Exception:
        pass

    try:
        if raw_data.get('CurrentLiabilities') is None:
            cl_components = [
                raw_data.get('AccountsPayable') or 0,
                raw_data.get('AccruedLiabilities') or 0,
                raw_data.get('ShortTermDebt') or 0,
                raw_data.get('CurrentPortionLongTermDebt') or 0,
                raw_data.get('DeferredRevenue') or 0
            ]
            if any(x != 0 for x in cl_components):
                raw_data['CurrentLiabilities'] = sum(cl_components)
                raw_data['_meta_inferred_CurrentLiabilities_from_components'] = True
    except Exception:
        pass

    # Recalculate total_debt and set meta
    try:
        lt = raw_data.get('LongTermDebt') or 0
        st = raw_data.get('ShortTermDebt') or 0
        cplt = raw_data.get('CurrentPortionLongTermDebt') or 0
        total_debt = lt + st + cplt
        raw_data['TotalDebt_Recalculated'] = total_debt
        raw_data['_meta_total_debt_recalculated'] = True
    except:
        pass

    # Recompute OperatingCashFlow if missing and sufficient components exist
    try:
        if raw_data.get('OperatingCashFlow') is None:
            ni = raw_data.get('NetIncome')
            dep = raw_data.get('DepreciationAmortization') or 0
            sbc = raw_data.get('StockBasedComp') or 0
            change_wc = raw_data.get('ChangeInWorkingCapital')
            # Heuristic: OCF ≈ NetIncome + Depreciation + SBC - ChangeInWorkingCapital + DeferredIncomeTaxes
            if ni is not None:
                deferred_taxes = raw_data.get('DeferredIncomeTaxes') or 0
                change_wc_val = change_wc if change_wc is not None else 0
                ocf_est = ni + dep + sbc - change_wc_val + deferred_taxes
                raw_data['OperatingCashFlow'] = ocf_est
                raw_data['_meta_inferred_OperatingCashFlow'] = True
    except:
        pass

    # CapitalExpenditures: if missing but InvestingCashFlow exists and components present, try to infer CAPEX sign convention
    try:
        if raw_data.get('CapitalExpenditures') is None and raw_data.get('InvestingCashFlow') is not None:
            # Conservative: if Investments and Acquisitions known, assume capex = negative of (investing cf + acquisitions + purchase_of_investments - sale_of_investments)
            investing_cf = raw_data.get('InvestingCashFlow') or 0
            acquisitions = raw_data.get('AcquisitionsCash') or 0
            purchase_of_investments = raw_data.get('PurchaseOfInvestments') or 0
            sale_of_investments = raw_data.get('SaleOfInvestments') or 0
            # This is a heuristic and we mark it
            capex_est = -(abs(investing_cf) - acquisitions - sale_of_investments + purchase_of_investments)
            # only set if non-zero
            if capex_est != 0:
                raw_data['CapitalExpenditures'] = capex_est
                raw_data['_meta_inferred_CapitalExpenditures_from_investing'] = True
    except:
        pass

    # Free cash flow: ensure present or recalc
    try:
        if raw_data.get('OperatingCashFlow') is not None and raw_data.get('CapitalExpenditures') is not None:
            try:
                raw_data['FreeCashFlow'] = raw_data['OperatingCashFlow'] - abs(raw_data['CapitalExpenditures'])
                raw_data['_meta_free_cash_flow_recalculated'] = True
            except:
                pass
    except:
        pass

    # Book value / equity components: if APIC/CommonStock/TreasuryStock missing but StockholdersEquity present and others present, attempt reconciliation
    try:
        if (raw_data.get('AdditionalPaidInCapital') is None or raw_data.get('CommonStock') is None or raw_data.get('TreasuryStock') is None) and raw_data.get('StockholdersEquity') is not None:
            # Try to compute missing components if retained earnings and accumulated OCI and noncontrolling interest present
            equity = raw_data.get('StockholdersEquity')
            retained = raw_data.get('RetainedEarnings') or 0
            acc_oci = raw_data.get('AccumulatedOCI') or 0
            noncont = raw_data.get('NoncontrollingInterest') or 0
            # We'll only infer APIC/Common/Treasury if exactly one is missing to avoid guessing.
            missing = [k for k in ('AdditionalPaidInCapital', 'CommonStock', 'TreasuryStock') if raw_data.get(k) is None]
            known_sum = retained + acc_oci + noncont
            if len(missing) == 1:
                inferred = equity - known_sum - (raw_data.get('AdditionalPaidInCapital') or 0) - (raw_data.get('CommonStock') or 0) - (raw_data.get('TreasuryStock') or 0)
                # Place inferred into the single missing field
                raw_data[missing[0]] = inferred
                raw_data[f'_meta_inferred_{missing[0]}'] = True
    except:
        pass

    # Validation and flags (after inferences)
    validation_issues = validate_fundamentals(raw_data)
    one_offs = flag_one_offs(raw_data)

    # Recalculate ratios using updated raw_data
    ratios = calculate_ratios(raw_data, industry)

    # EPS calculation: prefer NetIncomeAvailableToCommon then NetIncome; ensure shares exist
    shares = raw_data.get('SharesOutstanding') or raw_data.get('SharesOutstandingBasic') or raw_data.get('SharesOutstandingDiluted')
    net_income_for_eps = raw_data.get('NetIncomeAvailableToCommon') if raw_data.get('NetIncomeAvailableToCommon') is not None else raw_data.get('NetIncome')
    if shares and shares > 0 and net_income_for_eps is not None:
        try:
            eps_calc = net_income_for_eps / shares
            ratios['EPS_Calculated'] = round(eps_calc, 5)
        except:
            pass

    # Try fetch market data (Yahoo -> Nasdaq fallback)
    market = fetch_market_data(ticker.upper())
    market_based = {}
    try:
        share_price = market.get('share_price')
        market_cap = market.get('market_cap')
        # compute missing with shares if possible
        if market_cap is None and share_price is not None and shares:
            try:
                market_cap = share_price * shares
            except:
                pass
        if share_price is None and market_cap is not None and shares:
            try:
                share_price = market_cap / shares
            except:
                pass

        pe_ratio = None
        if market_cap and raw_data.get('NetIncome') and raw_data.get('NetIncome') != 0:
            try:
                pe_ratio = market_cap / raw_data['NetIncome']
            except:
                pe_ratio = None

        total_debt = (raw_data.get('LongTermDebt') or 0) + (raw_data.get('ShortTermDebt') or 0) + (raw_data.get('CurrentPortionLongTermDebt') or 0)
        cash = (raw_data.get('Cash') or 0) + (raw_data.get('RestrictedCash') or 0)
        enterprise_value = None
        if market_cap is not None:
            enterprise_value = market_cap + total_debt - cash

        ev_ebitda = None
        ebitda = ratios.get('EBITDA')
        if enterprise_value is not None and ebitda and ebitda != 0:
            try:
                ev_ebitda = enterprise_value / ebitda
            except:
                ev_ebitda = None

        market_based = {
            "share_price": share_price,
            "market_cap": market_cap,
            "currency": market.get("currency"),
            "pe_ratio": pe_ratio,
            "enterprise_value": enterprise_value,
            "ev_to_ebitda": ev_ebitda,
            "source": market.get("source"),
            "fetched_at": market.get("fetched_at")
        }
    except Exception:
        market_based = {
            "share_price": None,
            "market_cap": None,
            "currency": None,
            "pe_ratio": None,
            "enterprise_value": None,
            "ev_to_ebitda": None,
            "source": None,
            "fetched_at": None
        }

    # Present the main result with careful mapping and metadata
    data_quality = {
        "validation_issues": validation_issues if validation_issues else [],
        "one_off_flags": one_offs if one_offs else [],
        "data_complete": (len(validation_issues) == 0),
        "provenance_confirmed_annual_10k": True if raw_data.get("_report_end_date") else False,
        "report_end_date": raw_data.get("_report_end_date"),
        "market_data_provided": True if market_based.get("market_cap") or market_based.get("share_price") else False,
    }

    # fiscal_year_end formatting
    fye = company_info.get('fiscal_year_end')
    if isinstance(fye, str) and len(fye) == 4 and fye.isdigit():
        try:
            fye = f"{fye[:2]}-{fye[2:]}"
        except:
            pass

    # Flag for book value completeness
    book_components_missing = False
    if raw_data.get('CommonStock') is None or raw_data.get('AdditionalPaidInCapital') is None or raw_data.get('TreasuryStock') is None:
        book_components_missing = True

    result = {
        "ticker": ticker.upper(),
        "company_name": company_info.get('name'),
        "industry": industry,
        "sic_code": company_info.get('sic'),
        "sic_description": company_info.get('sic_description'),
        "fiscal_year_end": fye,
        "last_updated": datetime.utcnow().isoformat() + "Z",
        "data_source": "SEC EDGAR (Annual 10-K Data)",
        "market_data": market_based,

        "balance_sheet": {
            "assets": {
                "total_assets": raw_data.get('Assets'),
                "current_assets": raw_data.get('CurrentAssets'),
                "cash_and_equivalents": raw_data.get('Cash'),
                "restricted_cash": raw_data.get('RestrictedCash'),
                "short_term_investments": raw_data.get('ShortTermInvestments'),
                "accounts_receivable": raw_data.get('AccountsReceivable'),
                "inventory": raw_data.get('Inventory'),
                "prepaid_expenses": raw_data.get('PrepaidExpenses'),
                "other_current_assets": raw_data.get('OtherCurrentAssets'),
                "property_plant_equipment_net": raw_data.get('PropertyPlantEquipment'),
                "property_plant_equipment_gross": raw_data.get('PropertyPlantEquipmentGross'),
                "accumulated_depreciation_ppe": raw_data.get('AccumulatedDepreciationPPE'),
                "goodwill": raw_data.get('Goodwill'),
                "intangible_assets": raw_data.get('IntangibleAssets'),
                "long_term_investments": raw_data.get('LongTermInvestments'),
                "equity_method_investments": raw_data.get('EquityMethodInvestments'),
                "deferred_tax_assets": raw_data.get('DeferredTaxAssetsNoncurrent'),
                "other_noncurrent_assets": raw_data.get('OtherNoncurrentAssets'),
            },
            "liabilities": {
                "total_liabilities": raw_data.get('Liabilities'),
                "current_liabilities": raw_data.get('CurrentLiabilities'),
                "accounts_payable": raw_data.get('AccountsPayable'),
                "accrued_liabilities": raw_data.get('AccruedLiabilities'),
                "accrued_compensation": raw_data.get('AccruedCompensation'),
                "short_term_debt": raw_data.get('ShortTermDebt'),
                "current_portion_long_term_debt": raw_data.get('CurrentPortionLongTermDebt'),
                "long_term_debt": raw_data.get('LongTermDebt'),
                "total_debt": ratios.get('Total_Debt') or raw_data.get('TotalDebt_Recalculated'),
                "deferred_revenue": raw_data.get('DeferredRevenue'),
                "deferred_tax_liabilities": raw_data.get('DeferredTaxLiabilities'),
                "pension_liabilities": raw_data.get('PensionLiabilities'),
                "operating_lease_liability": raw_data.get('OperatingLeaseLiability'),
                "finance_lease_liability": raw_data.get('FinanceLeaseLiability'),
                "other_noncurrent_liabilities": raw_data.get('OtherNoncurrentLiabilities'),
            },
            "equity": {
                "stockholders_equity": raw_data.get('StockholdersEquity'),
                "common_stock": raw_data.get('CommonStock'),
                "preferred_stock": raw_data.get('PreferredStock'),
                "additional_paid_in_capital": raw_data.get('AdditionalPaidInCapital'),
                "retained_earnings": raw_data.get('RetainedEarnings'),
                "treasury_stock": raw_data.get('TreasuryStock'),
                "accumulated_oci": raw_data.get('AccumulatedOCI'),
                "noncontrolling_interest": raw_data.get('NoncontrollingInterest'),
            }
        },

        "income_statement": {
            "revenue": raw_data.get('Revenue'),
            "cost_of_revenue": raw_data.get('CostOfRevenue'),
            "gross_profit": raw_data.get('GrossProfit'),
            "operating_expenses": raw_data.get('OperatingExpenses'),
            "research_development": raw_data.get('ResearchDevelopment'),
            "selling_general_admin": raw_data.get('SellingGeneralAdmin'),
            "marketing_expense": raw_data.get('MarketingExpense'),
            "general_admin_expense": raw_data.get('GeneralAdminExpense'),
            "restructuring_charges": raw_data.get('RestructuringCharges'),
            "impairment_charges": raw_data.get('ImpairmentCharges'),
            "operating_income": raw_data.get('OperatingIncome'),
            "ebit": ratios.get('EBIT'),
            "ebitda": ratios.get('EBITDA'),
            "interest_expense": raw_data.get('InterestExpense'),
            "interest_income": raw_data.get('InterestIncome'),
            "other_income_expense": raw_data.get('OtherIncome'),
            "gain_loss_on_investments": raw_data.get('GainLossOnInvestments'),
            "pretax_income": raw_data.get('PreTaxIncome'),
            "tax_expense": raw_data.get('TaxExpense'),
            "effective_tax_rate_pct": raw_data.get('EffectiveTaxRate') or ratios.get('Effective_Tax_Rate'),
            "net_income": raw_data.get('NetIncome'),
            "net_income_available_to_common": raw_data.get('NetIncomeAvailableToCommon'),
            "comprehensive_income": raw_data.get('ComprehensiveIncome'),
            "eps_diluted": raw_data.get('EPS'),
            "eps_basic": raw_data.get('EPSBasic'),
        },

        "cash_flow": {
            "operating_activities": {
                "operating_cash_flow": raw_data.get('OperatingCashFlow'),
                "depreciation_amortization": raw_data.get('DepreciationAmortization'),
                "amortization": raw_data.get('Amortization'),
                "stock_based_compensation": raw_data.get('StockBasedComp'),
                "deferred_income_taxes": raw_data.get('DeferredIncomeTaxes'),
                "change_in_working_capital": raw_data.get('ChangeInWorkingCapital'),
                "change_in_accounts_receivable": raw_data.get('ChangeInAR'),
                "change_in_inventory": raw_data.get('ChangeInInventory'),
                "change_in_accounts_payable": raw_data.get('ChangeInAP'),
                "change_in_accrued_liabilities": raw_data.get('ChangeInAccruedLiabilities'),
            },
            "investing_activities": {
                "capital_expenditures": raw_data.get('CapitalExpenditures'),
                "acquisitions": raw_data.get('AcquisitionsCash'),
                "proceeds_from_asset_sales": raw_data.get('ProceedsFromAssetSales'),
                "purchase_of_investments": raw_data.get('PurchaseOfInvestments'),
                "sale_of_investments": raw_data.get('SaleOfInvestments'),
                "investing_cash_flow": raw_data.get('InvestingCashFlow'),
            },
            "financing_activities": {
                "dividends_paid": raw_data.get('DividendsPaid'),
                "stock_repurchase": raw_data.get('StockRepurchase'),
                "proceeds_from_stock_issuance": raw_data.get('ProceedsFromStockIssuance'),
                "debt_issuance": raw_data.get('DebtIssuance'),
                "debt_repayment": raw_data.get('DebtRepayment'),
                "financing_cash_flow": raw_data.get('FinancingCashFlow'),
            },
            "free_cash_flow": raw_data.get('FreeCashFlow') or ratios.get('Free_Cash_Flow'),
        },

        "profitability_ratios": {
            "gross_margin_pct": ratios.get('Gross_Margin'),
            "operating_margin_pct": ratios.get('Operating_Margin'),
            "ebitda_margin_pct": ratios.get('EBITDA_Margin'),
            "pretax_margin_pct": ratios.get('Pretax_Margin'),
            "net_margin_pct": ratios.get('Net_Margin'),
            "roe_pct": ratios.get('ROE'),
            "roa_pct": ratios.get('ROA'),
            "fcf_margin_pct": ratios.get('FCF_Margin'),
            "operating_cash_flow_margin_pct": ratios.get('Operating_Cash_Flow_Margin'),
        },

        "leverage_ratios": {
            "debt_to_equity": ratios.get('Debt_to_Equity'),
            "debt_to_ebitda": ratios.get('Debt_to_EBITDA'),
            "debt_to_assets": ratios.get('Debt_to_Assets'),
            "interest_coverage": ratios.get('Interest_Coverage'),
            "interest_coverage_note": ratios.get('Interest_Coverage_Note'),
        },

        "liquidity_ratios": {
            "current_ratio": ratios.get('Current_Ratio'),
            "quick_ratio": ratios.get('Quick_Ratio'),
            "cash_ratio": ratios.get('Cash_Ratio'),
            "working_capital": ratios.get('Working_Capital'),
        },

        "efficiency_ratios": {
            "asset_turnover": ratios.get('Asset_Turnover'),
            "receivables_turnover": ratios.get('Receivables_Turnover'),
            "days_sales_outstanding": ratios.get('Days_Sales_Outstanding'),
            "inventory_turnover": ratios.get('Inventory_Turnover'),
            "days_inventory_outstanding": ratios.get('Days_Inventory_Outstanding'),
            "payables_turnover": ratios.get('Payables_Turnover'),
            "days_payable_outstanding": ratios.get('Days_Payable_Outstanding'),
            "cash_conversion_cycle": ratios.get('Cash_Conversion_Cycle'),
        },

        "per_share_metrics": {
            "shares_outstanding": shares,
            "eps_diluted": raw_data.get('EPS'),
            "eps_basic": raw_data.get('EPSBasic'),
            "eps_calculated": ratios.get('EPS_Calculated'),
            "book_value_per_share": ratios.get('Book_Value_Per_Share'),
            "revenue_per_share": ratios.get('Revenue_Per_Share'),
            "cash_flow_per_share": ratios.get('Cash_Flow_Per_Share'),
            "dividend_per_share": ratios.get('Dividend_Per_Share'),
        },

        "cash_flow_metrics": {
            "fcf_to_net_income": ratios.get('FCF_to_Net_Income'),
            "dividend_payout_ratio_pct": ratios.get('Dividend_Payout_Ratio'),
        },

        "data_quality": data_quality,
        "_meta_book_value_components_missing": book_components_missing
    }

    # industry-specific metrics preserved
    if industry == "Bank":
        result["banking_metrics"] = {
            "interest_income": raw_data.get('InterestIncomeBank') or raw_data.get('InterestIncome'),
            "interest_expense": raw_data.get('InterestExpenseBank') or raw_data.get('InterestExpense'),
            "net_interest_income": raw_data.get('NetInterestIncome'),
            "provision_loan_losses": raw_data.get('ProvisionLoanLosses'),
            "non_interest_income": raw_data.get('NonInterestIncome'),
            "loans_gross": raw_data.get('LoansGross'),
            "loans_net": raw_data.get('Loans'),
            "deposits": raw_data.get('Deposits'),
            "allowance_loan_losses": raw_data.get('AllowanceLoanLosses'),
            "net_interest_margin_pct": ratios.get('Net_Interest_Margin'),
            "loan_to_deposit_pct": ratios.get('Loan_to_Deposit'),
            "equity_to_assets_pct": ratios.get('Equity_to_Assets'),
        }

    elif industry == "REIT":
        occupancy_data = None
        try:
            occ_result = get_occupancy_rate(ticker)
            if "occupancy_rate" in occ_result:
                occupancy_data = {
                    "occupancy_rate_pct": occ_result["occupancy_rate"],
                    "source": occ_result.get("source"),
                    "context": occ_result.get("context"),
                    "filing_url": occ_result.get("filing_url")
                }
        except:
            pass

        result["reit_metrics"] = {
            "real_estate_investments_net": raw_data.get('RealEstateInvestments'),
            "real_estate_at_cost": raw_data.get('RealEstateAtCost'),
            "accumulated_depreciation": raw_data.get('AccumulatedDepreciationRE'),
            "rental_income": raw_data.get('RentalIncome'),
            "property_operating_expense": raw_data.get('PropertyOperatingExpense'),
            "noi": raw_data.get('NOI'),
            "funds_from_operations": raw_data.get('FFO'),
            "adjusted_ffo": raw_data.get('AFFO'),
            "number_of_properties": raw_data.get('NumberOfProperties'),
            "square_footage": raw_data.get('SquareFootage'),
            "ffo_per_share": ratios.get('FFO_Per_Share'),
            "affo_per_share": ratios.get('AFFO_Per_Share'),
            "debt_to_real_estate": ratios.get('Debt_to_Real_Estate'),
            "occupancy": occupancy_data,
        }

    elif industry == "Insurance":
        result["insurance_metrics"] = {
            "premiums_earned": raw_data.get('PremiumsEarned'),
            "premiums_written": raw_data.get('PremiumsWritten'),
            "losses_claims": raw_data.get('LossesClaims'),
            "policyholder_benefits": raw_data.get('PolicyholderBenefits'),
            "investment_income": raw_data.get('InvestmentIncomeInsurance'),
            "reinsurance_recoverables": raw_data.get('ReinsuranceRecoverables'),
            "loss_ratio_pct": ratios.get('Loss_Ratio'),
        }

    elif industry == "Utility":
        result["utility_metrics"] = {
            "regulated_revenue": raw_data.get('RegulatedRevenue'),
            "regulatory_assets": raw_data.get('RegulatoryAssets'),
            "regulatory_liabilities": raw_data.get('RegulatoryLiabilities'),
        }

    elif industry == "Energy":
        result["energy_metrics"] = {
            "proved_reserves": raw_data.get('ProvedReserves'),
            "exploration_expense": raw_data.get('ExplorationExpense'),
        }

    return result


def get_fundamentals(ticker):
    now = time()
    cache_key = ticker.upper()
    if cache_key in CACHE and now - CACHE[cache_key]["timestamp"] < CACHE_TTL:
        return CACHE[cache_key]["data"]
    else:
        data = fetch_comprehensive_fundamentals(ticker)
        CACHE[cache_key] = {"timestamp": now, "data": data}
        return data


@app.route('/', methods=['GET'])
def home():
    return jsonify({
        "message": "SEC Financial Data API",
        "version": "2.2",
        "data_source": "SEC EDGAR (Annual 10-K Reports)",
        "endpoints": {
            "GET /api/fundamentals/<ticker>": "Get comprehensive financial fundamentals with industry-specific metrics",
            "GET /api/occupancy/<ticker>": "Get REIT occupancy rate (also included in fundamentals for REITs)",
            "POST /api/occupancy": "Post {'ticker': 'STAG'} for occupancy"
        },
        "features": [
            "100% SEC EDGAR data (no third-party APIs for fundamentals)",
            "Consistent annual (10-K) period data to prevent metric mixing",
            "Data validation to catch impossible values and missing critical fields",
            "Comprehensive balance sheet, income statement, cash flow",
            "Industry-specific metrics (Banks, REITs, Insurance, etc.)",
            "Automatic industry detection via SIC codes",
            "Market data (best-effort) to compute PE/EV where available (Yahoo -> Nasdaq fallback)",
            "One-off detection flags to avoid misleading trend analysis",
            "Standardized schema for consistent downstream processing",
            "30+ calculated ratios with validation"
        ]
    })


@app.route('/api/occupancy/<ticker>', methods=['GET'])
def api_occupancy(ticker):
    result = get_occupancy_rate(ticker)
    return jsonify(result), 200 if "error" not in result else 404


@app.route('/api/occupancy', methods=['POST'])
def api_occupancy_post():
    data = request.get_json()
    if not data or 'ticker' not in data:
        return jsonify({"error": "Missing 'ticker'"}), 400
    result = get_occupancy_rate(data['ticker'])
    return jsonify(result), 200 if "error" not in result else 404


@app.route('/api/fundamentals/<ticker>', methods=['GET'])
def api_fundamentals(ticker):
    result = get_fundamentals(ticker.upper())
    if "error" in result:
        return jsonify(result), 404
    return jsonify(result), 200


def run_basic_checks(tickers=None):
    """
    Basic integration checks ("triple-tested" smoke tests).
    Runs get_fundamentals for a small list of tickers and reports presence of:
    - Revenue, NetIncome, Assets, SharesOutstanding
    - Market data (share_price or market_cap)
    - No mixed periods (report_end_date present)
    Print a simple pass/fail summary.
    """
    if tickers is None:
        tickers = ["AAPL", "O", "MSFT"]
    summary = []
    for t in tickers:
        try:
            print(f"Running checks for {t} ...")
            res = get_fundamentals(t)
            dq = res.get("data_quality", {})
            missing = []
            for field in ["income_statement", "balance_sheet", "per_share_metrics"]:
                if field not in res:
                    missing.append(field)
            critical_missing = []
            if not res.get("income_statement", {}).get("revenue"):
                critical_missing.append("Revenue")
            if not res.get("income_statement", {}).get("net_income"):
                critical_missing.append("NetIncome")
            if not res.get("balance_sheet", {}).get("assets", {}).get("total_assets"):
                critical_missing.append("Assets")
            if not res.get("per_share_metrics", {}).get("shares_outstanding"):
                critical_missing.append("SharesOutstanding")
            market_ok = res.get("market_data", {}).get("market_cap") or res.get("market_data", {}).get("share_price")
            report_ok = dq.get("provenance_confirmed_annual_10k", False)
            test_result = {
                "ticker": t,
                "critical_missing": critical_missing,
                "market_data_present": bool(market_ok),
                "report_end_date": res.get("data_quality", {}).get("report_end_date"),
                "validation_issues": dq.get("validation_issues"),
                "one_off_flags": dq.get("one_off_flags"),
            }
            summary.append(test_result)
            print("Result:", test_result)
        except Exception as e:
            print(f"Error testing {t}: {e}")
            summary.append({"ticker": t, "error": str(e)})
    return summary


if __name__ == "__main__":
    # If run with --test, run basic checks; otherwise start the Flask app.
    if len(sys.argv) > 1 and sys.argv[1].lower() in ("--test", "test"):
        print("Running basic smoke tests (best-effort network calls). This will call SEC and Yahoo endpoints.")
        results = run_basic_checks()
        print("\nSMOKE TEST SUMMARY:")
        for r in results:
            print(r)
        sys.exit(0)
    else:
        app.run(debug=False, host='0.0.0.0', port=5000)
