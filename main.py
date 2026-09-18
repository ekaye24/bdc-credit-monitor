def fetch_sec_edgar_events(start_dt, end_dt):
    """Queries SEC EDGAR API with tightened high-conviction credit distress phrases."""
    results = []
    base_url = "https://efts.sec.gov/LATEST/search-index"
    
    # High-conviction multi-word credit distress phrases
    phrases = [
        '"restructuring support agreement"',
        '"forbearance agreement"',
        '"event of default"',
        '"debtor-in-possession"',
        '"voluntary petition under chapter 11"',
        '"going concern qualification"'
    ]
    
    headers = {"User-Agent": "BDCCreditSurveillance/1.0 (ethankaye92@gmail.com)"}
    start_str = start_dt.strftime("%Y-%m-%d")
    end_str = end_dt.strftime("%Y-%m-%d")

    for phrase in phrases:
        params = {
            "q": phrase,
            "forms": "8-K",
            "startdt": start_str,
            "enddt": end_str
        }
        url = f"{base_url}?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req) as response:
                if response.status == 200:
                    data = json.loads(response.read().decode())
                    hits = data.get("hits", {}).get("hits", [])
                    for hit in hits:
                        src = hit.get("_source", {})
                        
                        display_names = src.get("display_names", [])
                        if display_names:
                            entity_name = display_names[0].split("  (")[0].strip()
                        else:
                            entity_name = src.get("entity_name", "Unknown SEC Filer")
                        
                        # Apply Exclusion Filter
                        if is_excluded_entity(entity_name):
                            continue
                        
                        cik_list = src.get("ciks", [])
                        cik = cik_list[0] if cik_list else src.get("cik", "")
                        adsh_raw = src.get("adsh", "")
                        adsh_clean = adsh_raw.replace("-", "")
                        
                        if cik and adsh_raw:
                            doc_url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{adsh_clean}/{adsh_raw}.txt"
                        else:
                            doc_url = "https://www.sec.gov/edgar/searchedgar/companysearch"
                        
                        results.append({
                            "entity": entity_name,
                            "phrase": phrase.replace('"', ''),
                            "form": "8-K",
                            "url": doc_url
                        })
        except Exception as e:
            print(f"SEC EDGAR search notice for {phrase}: {e}")
            
    return results
