"""
CSV Import Script for NoteHelper Alignment Sheet
Imports organizational structure and customer data from alignment CSV.
"""
import csv
import sys
from app import create_app
from app.models import db, POD, SolutionEngineer, Vertical, Territory, Seller, Customer

app = create_app()


def import_alignment_sheet(csv_path: str):
    """Import data from alignment sheet CSV."""
    print(f"Reading CSV from: {csv_path}")
    
    # Try different encodings
    encodings = ['utf-8-sig', 'utf-8', 'latin-1', 'cp1252']
    rows = None
    
    for encoding in encodings:
        try:
            with open(csv_path, 'r', encoding=encoding) as f:
                reader = csv.DictReader(f)
                rows = list(reader)
            print(f"Successfully read CSV with encoding: {encoding}")
            break
        except UnicodeDecodeError:
            continue
    
    if rows is None:
        raise ValueError("Could not read CSV with any supported encoding")
    
    print(f"Found {len(rows)} rows in CSV")
    
    with app.app_context():
        # Track created entities to avoid duplicates
        territories_map = {}
        sellers_map = {}
        pods_map = {}
        solution_engineers_map = {}
        verticals_map = {}
        
        # Step 1: Create Territories
        print("\n=== Creating Territories ===")
        territory_names = set()
        for row in rows:
            territory_name = row.get('Sales Territory', '').strip()
            if territory_name:
                territory_names.add(territory_name)
        
        for territory_name in sorted(territory_names):
            if territory_name not in territories_map:
                territory = Territory(name=territory_name)
                db.session.add(territory)
                territories_map[territory_name] = territory
                print(f"Created territory: {territory_name}")
        
        db.session.flush()
        
        # Step 2: Create Sellers with type and alias
        print("\n=== Creating Sellers ===")
        seller_names = set()
        for row in rows:
            seller_name = row.get('DSS (Growth/Acq)', '').strip()
            if seller_name:
                seller_names.add(seller_name)
        
        for seller_name in sorted(seller_names):
            if seller_name not in sellers_map:
                # Find a row with this seller to get type and alias
                seller_row = next((r for r in rows if r.get('DSS (Growth/Acq)', '').strip() == seller_name), None)
                
                if seller_row:
                    # Determine seller type and alias
                    growth_dss = seller_row.get('Primary Cloud & AI DSS', '').strip()
                    acq_dss = seller_row.get('Primary Cloud & AI-Acq DSS', '').strip()
                    
                    if growth_dss:
                        seller_type = 'Growth'
                        alias = growth_dss.lower()
                    elif acq_dss:
                        seller_type = 'Acquisition'
                        alias = acq_dss.lower()
                    else:
                        seller_type = 'Growth'  # Default
                        alias = None
                    
                    seller = Seller(
                        name=seller_name,
                        seller_type=seller_type,
                        alias=alias
                    )
                    db.session.add(seller)
                    sellers_map[seller_name] = seller
                    print(f"Created seller: {seller_name} ({seller_type}, alias: {alias})")
        
        db.session.flush()
        
        # Step 3: Associate Sellers with Territories
        print("\n=== Associating Sellers with Territories ===")
        for row in rows:
            seller_name = row.get('DSS (Growth/Acq)', '').strip()
            territory_name = row.get('Sales Territory', '').strip()
            
            if seller_name and territory_name:
                seller = sellers_map.get(seller_name)
                territory = territories_map.get(territory_name)
                
                if seller and territory and territory not in seller.territories:
                    seller.territories.append(territory)
                    print(f"Associated {seller_name} with {territory_name}")
        
        db.session.flush()
        
        # Step 4: Create PODs
        print("\n=== Creating PODs ===")
        pod_names = set()
        for row in rows:
            pod_name = row.get('SME&C POD', '').strip()
            if pod_name:
                pod_names.add(pod_name)
        
        for pod_name in sorted(pod_names):
            if pod_name not in pods_map:
                pod = POD(name=pod_name)
                db.session.add(pod)
                pods_map[pod_name] = pod
                print(f"Created POD: {pod_name}")
        
        db.session.flush()
        
        # Step 5: Associate Territories with PODs
        print("\n=== Associating Territories with PODs ===")
        for territory_name, territory in territories_map.items():
            # Find a row with this territory to get its POD
            territory_row = next((r for r in rows if r.get('Sales Territory', '').strip() == territory_name), None)
            
            if territory_row:
                pod_name = territory_row.get('SME&C POD', '').strip()
                if pod_name:
                    pod = pods_map.get(pod_name)
                    if pod:
                        territory.pod = pod
                        print(f"Associated territory {territory_name} with POD {pod_name}")
        
        db.session.flush()
        
        # Step 6: Create Solution Engineers - Data
        print("\n=== Creating Data Solution Engineers ===")
        # Collect SE info with all their PODs
        data_se_info = {}  # {se_name: {'alias': str, 'pods': set()}}
        for row in rows:
            se_name = row.get('Data SE', '').strip()
            if se_name:
                if se_name not in data_se_info:
                    alias = row.get('Primary Cloud & AI Data DSE', '').strip().lower()
                    data_se_info[se_name] = {'alias': alias, 'pods': set()}
                
                pod_name = row.get('SME&C POD', '').strip()
                if pod_name and pod_name in pods_map:
                    data_se_info[se_name]['pods'].add(pod_name)
        
        for se_name, info in sorted(data_se_info.items()):
            if se_name not in solution_engineers_map:
                se = SolutionEngineer(
                    name=se_name,
                    alias=info['alias'] if info['alias'] else None,
                    specialty='Azure Data'
                )
                # Associate with all PODs
                for pod_name in info['pods']:
                    se.pods.append(pods_map[pod_name])
                
                db.session.add(se)
                solution_engineers_map[se_name] = se
                pods_list = ', '.join(sorted(info['pods']))
                print(f"Created Data SE: {se_name} (alias: {info['alias']}, PODs: {pods_list})")
        
        # Step 7: Create Solution Engineers - Infra
        print("\n=== Creating Infra Solution Engineers ===")
        # Collect SE info with all their PODs
        infra_se_info = {}  # {se_name: {'alias': str, 'pods': set()}}
        for row in rows:
            se_name = row.get('Infra SE', '').strip()
            if se_name:
                if se_name not in infra_se_info:
                    alias = row.get('Primary Cloud & AI Infrastructure DSE', '').strip().lower()
                    infra_se_info[se_name] = {'alias': alias, 'pods': set()}
                
                pod_name = row.get('SME&C POD', '').strip()
                if pod_name and pod_name in pods_map:
                    infra_se_info[se_name]['pods'].add(pod_name)
        
        for se_name, info in sorted(infra_se_info.items()):
            if se_name not in solution_engineers_map:
                se = SolutionEngineer(
                    name=se_name,
                    alias=info['alias'] if info['alias'] else None,
                    specialty='Azure Core and Infra'
                )
                # Associate with all PODs
                for pod_name in info['pods']:
                    se.pods.append(pods_map[pod_name])
                
                db.session.add(se)
                solution_engineers_map[se_name] = se
                pods_list = ', '.join(sorted(info['pods']))
                print(f"Created Infra SE: {se_name} (alias: {info['alias']}, PODs: {pods_list})")
        
        # Step 8: Create Solution Engineers - Apps
        print("\n=== Creating Apps Solution Engineers ===")
        # Collect SE info with all their PODs
        apps_se_info = {}  # {se_name: {'alias': str, 'pods': set()}}
        for row in rows:
            se_name = row.get('Apps SE', '').strip()
            if se_name:
                if se_name not in apps_se_info:
                    alias = row.get('Primary Cloud & AI Apps DSE', '').strip().lower()
                    apps_se_info[se_name] = {'alias': alias, 'pods': set()}
                
                pod_name = row.get('SME&C POD', '').strip()
                if pod_name and pod_name in pods_map:
                    apps_se_info[se_name]['pods'].add(pod_name)
        
        for se_name, info in sorted(apps_se_info.items()):
            if se_name not in solution_engineers_map:
                se = SolutionEngineer(
                    name=se_name,
                    alias=info['alias'] if info['alias'] else None,
                    specialty='Azure Apps and AI'
                )
                # Associate with all PODs
                for pod_name in info['pods']:
                    se.pods.append(pods_map[pod_name])
                
                db.session.add(se)
                solution_engineers_map[se_name] = se
                pods_list = ', '.join(sorted(info['pods']))
                print(f"Created Apps SE: {se_name} (alias: {info['alias']}, PODs: {pods_list})")
        
        db.session.flush()
        
        # Step 9: Create Verticals (track unique vertical + category combinations)
        print("\n=== Creating Verticals ===")
        vertical_combinations = set()
        for row in rows:
            vertical = row.get('Vertical', '').strip()
            category = row.get('Vertical Category', '').strip()
            if vertical:
                vertical_combinations.add((vertical, category if category else None))
        
        for vertical_name, category in sorted(vertical_combinations):
            key = f"{vertical_name}|{category}" if category else vertical_name
            if key not in verticals_map:
                vertical = Vertical(name=vertical_name, category=category)
                db.session.add(vertical)
                verticals_map[key] = vertical
                print(f"Created vertical: {vertical_name}" + (f" - {category}" if category else ""))
        
        db.session.flush()
        
        # Step 10: Create Customers
        print("\n=== Creating Customers ===")
        customers_created = 0
        customers_skipped = 0
        
        for idx, row in enumerate(rows, 1):
            customer_name = row.get('Customer Name', '').strip()
            tpid_str = row.get('TPID', '').strip()
            
            if not customer_name or not tpid_str:
                print(f"Row {idx}: Skipping - missing customer name or TPID")
                customers_skipped += 1
                continue
            
            try:
                tpid = int(tpid_str)
            except ValueError:
                print(f"Row {idx}: Skipping - invalid TPID: {tpid_str}")
                customers_skipped += 1
                continue
            
            # Check if customer already exists
            existing = Customer.query.filter_by(tpid=tpid).first()
            if existing:
                print(f"Row {idx}: Skipping - customer with TPID {tpid} already exists")
                customers_skipped += 1
                continue
            
            territory_name = row.get('Sales Territory', '').strip()
            seller_name = row.get('DSS (Growth/Acq)', '').strip()
            vertical_name = row.get('Vertical', '').strip()
            category = row.get('Vertical Category', '').strip()
            
            territory = territories_map.get(territory_name)
            seller = sellers_map.get(seller_name)
            
            customer = Customer(
                name=customer_name,
                tpid=tpid,
                territory=territory,
                seller=seller
            )
            
            # Add vertical if exists
            if vertical_name:
                key = f"{vertical_name}|{category}" if category else vertical_name
                vertical = verticals_map.get(key)
                if vertical:
                    customer.verticals.append(vertical)
            
            db.session.add(customer)
            customers_created += 1
            
            if customers_created % 50 == 0:
                print(f"Created {customers_created} customers...")
        
        # Commit all changes
        print("\n=== Committing to database ===")
        db.session.commit()
        
        print(f"\n=== Import Complete ===")
        print(f"Territories: {len(territories_map)}")
        print(f"Sellers: {len(sellers_map)}")
        print(f"PODs: {len(pods_map)}")
        print(f"Solution Engineers: {len(solution_engineers_map)}")
        print(f"Verticals: {len(verticals_map)}")
        print(f"Customers: {customers_created} created, {customers_skipped} skipped")


if __name__ == '__main__':
    if len(sys.argv) != 2:
        print("Usage: python import_alignment_sheet.py <path_to_csv>")
        sys.exit(1)
    
    csv_path = sys.argv[1]
    
    try:
        import_alignment_sheet(csv_path)
        print("\n✓ Import completed successfully!")
    except Exception as e:
        print(f"\n✗ Import failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
