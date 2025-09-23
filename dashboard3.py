import streamlit as st
import boto3
import json
import pandas as pd
import plotly.express as px
from datetime import datetime, timedelta

# -------------------------------
# Streamlit Page Configuration
# -------------------------------
st.set_page_config(
    page_title="AWS Cost Optimization Dashboard",
    page_icon="💰",
    layout="wide"
)

# -------------------------------
# AWS Clients
# -------------------------------
@st.cache_resource
def get_aws_clients():
    return {
        "s3": boto3.client("s3"),
        "lambda": boto3.client("lambda"),
        "ce": boto3.client("ce"),
        "ec2": boto3.client("ec2")
    }

# -------------------------------
# Helper: Read JSON from S3
# -------------------------------
def get_lambda_results_from_s3(bucket_name, key):
    try:
        clients = get_aws_clients()
        response = clients["s3"].get_object(Bucket=bucket_name.strip(), Key=key.strip())
        data = json.loads(response["Body"].read())
        return data
    except Exception as e:
        st.error(f"Error reading from S3: {str(e)}")
        return None

# -------------------------------
# Helper: Fetch Cost Explorer Data
# -------------------------------
def fetch_cost_explorer_data(start_date=None, end_date=None, granularity="DAILY"):
    ce = get_aws_clients()["ce"]

    if not end_date:
        end_date = datetime.utcnow().date()
    if not start_date:
        start_date = end_date - timedelta(days=7)

    response = ce.get_cost_and_usage(
        TimePeriod={
            "Start": start_date.strftime("%Y-%m-%d"),
            "End": end_date.strftime("%Y-%m-%d")
        },
        Granularity=granularity,
        Metrics=["UnblendedCost"],
        GroupBy=[{"Type": "DIMENSION", "Key": "SERVICE"}]
    )

    rows = []
    for result in response["ResultsByTime"]:
        time_period = result["TimePeriod"]["Start"]
        for group in result.get("Groups", []):
            service = group["Keys"][0]
            amount = float(group["Metrics"]["UnblendedCost"]["Amount"])
            rows.append({"Date": time_period, "Service": service, "Cost": amount})

    return pd.DataFrame(rows)

# -------------------------------
# Helper: Detect Stale Resources with Cost Estimation
# -------------------------------
def detect_stale_resources_with_cost():
    clients = get_aws_clients()
    ec2 = clients["ec2"]

    # Pricing assumptions
    EBS_COST_PER_GB = 0.10
    EIP_COST_PER_MONTH = 3.6
    SNAPSHOT_COST_PER_GB = 0.05

    # 1️⃣ Unattached EBS Volumes
    volumes = ec2.describe_volumes(Filters=[{"Name": "status", "Values": ["available"]}])
    unattached_volumes = [
        {
            "VolumeId": v["VolumeId"],
            "Size (GiB)": v["Size"],
            "CreationDate": v["CreateTime"].strftime("%Y-%m-%d"),
            "Region": ec2.meta.region_name,
            "EstimatedMonthlyCost($)": round(v["Size"] * EBS_COST_PER_GB, 2)
        }
        for v in volumes["Volumes"]
    ]

    # 2️⃣ Unassociated Elastic IPs
    addresses = ec2.describe_addresses()
    unassociated_eips = [
        {
            "PublicIp": addr["PublicIp"],
            "AllocationId": addr["AllocationId"],
            "Domain": addr.get("Domain", "N/A"),
            "EstimatedMonthlyCost($)": EIP_COST_PER_MONTH
        }
        for addr in addresses["Addresses"] if "InstanceId" not in addr
    ]

    # 3️⃣ Old Snapshots (older than 60 days
    snapshots = ec2.describe_snapshots(OwnerIds=['self'])
    cutoff_date = datetime.utcnow() - timedelta(days=60)
    old_snapshots = [
        {
            "SnapshotId": s["SnapshotId"],
            "VolumeId": s["VolumeId"],
            "StartTime": s["StartTime"].strftime("%Y-%m-%d"),
            "State": s["State"],
            "Size (GiB)": s.get("VolumeSize", 0),
            "EstimatedMonthlyCost($)": round(s.get("VolumeSize", 0) * SNAPSHOT_COST_PER_GB, 2)
        }
        for s in snapshots["Snapshots"] if s["StartTime"].replace(tzinfo=None) < cutoff_date
    ]

    total_savings = sum(v["EstimatedMonthlyCost($)"] for v in unattached_volumes) \
                    + sum(e["EstimatedMonthlyCost($)"] for e in unassociated_eips) \
                    + sum(s["EstimatedMonthlyCost($)"] for s in old_snapshots)

    return unattached_volumes, unassociated_eips, old_snapshots, total_savings

# -------------------------------
# Initialize Session State
# -------------------------------
if "idle_data" not in st.session_state:
    st.session_state.idle_data = None
if "cost_data" not in st.session_state:
    st.session_state.cost_data = None
if "stale_data" not in st.session_state:
    st.session_state.stale_data = None

# -------------------------------
# Main Dashboard
# -------------------------------
st.title("💰 AWS Cost Optimization Dashboard")

# -------------------------------
# SECTION 1: Idle EC2 Analysis
# -------------------------------
st.header("🔍 EC2 Idle Instance Analysis")
col1, col2 = st.columns([3, 1])
with col1:
    s3_bucket = st.text_input("S3 Bucket Name", value="cost-optimization-data-s3")
with col2:
    s3_key = st.text_input("S3 Key", value="lambda-outputs/idle-instance-analysis.json")

if st.button("Refresh Idle EC2 Analysis"):
    st.session_state.idle_data = get_lambda_results_from_s3(s3_bucket, s3_key)

data = st.session_state.idle_data or get_lambda_results_from_s3(s3_bucket, s3_key)

if data:
    summary = data.get("summary", {})
    metadata = data.get("metadata", {})

    st.subheader("📈 Analysis Summary")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Instances", summary.get("total_instances_analyzed", 0))
    c2.metric("Idle Instances", summary.get("idle_instances", 0))
    c3.metric("Active Instances", summary.get("active_instances", 0))
    c4.metric("Potential Savings", f"${summary.get('potential_monthly_savings', 0):,.2f}")

    st.caption(f"📅 Last updated: {metadata.get('timestamp','N/A')}")
else:
    st.info("No idle instance data found in S3.")

# -------------------------------
# SECTION 2: AWS Cost Explorer
# -------------------------------
st.header("💵 AWS Cost Explorer Breakdown")
col1, col2 = st.columns(2)
with col1:
    start_date = st.date_input("Start Date", datetime.utcnow().date() - timedelta(days=7))
with col2:
    end_date = st.date_input("End Date", datetime.utcnow().date())

if start_date >= end_date:
    st.error("End Date must be after Start Date")
else:
    # Refresh Cost Explorer Data
    if st.button("Refresh Cost Explorer Data"):
        st.session_state.cost_data = fetch_cost_explorer_data(start_date=start_date, end_date=end_date)

    # Load data safely
    if st.session_state.cost_data is None:
        df_cost = fetch_cost_explorer_data(start_date=start_date, end_date=end_date)
    else:
        df_cost = st.session_state.cost_data

    if not df_cost.empty:
        total_cost = df_cost["Cost"].sum()
        st.metric(f"Total Cost ({start_date} → {end_date})", f"${total_cost:,.2f}")
        service_summary = df_cost.groupby("Service")["Cost"].sum().reset_index()
        st.subheader("📋 Cost by Service")
        st.dataframe(service_summary.sort_values("Cost", ascending=False))

        col1, col2 = st.columns(2)
        with col1:
            fig_pie = px.pie(service_summary, values="Cost", names="Service",
                             title=f"Cost by AWS Service ({start_date} → {end_date})")
            st.plotly_chart(fig_pie, use_container_width=True)
        with col2:
            fig_line = px.line(df_cost, x="Date", y="Cost", color="Service",
                               title=f"Daily Cost by Service ({start_date} → {end_date})")
            st.plotly_chart(fig_line, use_container_width=True)
    else:
        st.warning("No cost data available. Make sure Cost Explorer is enabled.")

# -------------------------------
# SECTION 3: Stale Resource Detection
# -------------------------------
st.header("🛠️ Stale Resource Detection & Cost Savings")
if st.button("Detect Stale Resources & Estimate Savings"):
    st.session_state.stale_data = detect_stale_resources_with_cost()

if st.session_state.stale_data:
    unattached_volumes, unassociated_eips, old_snapshots, total_savings = st.session_state.stale_data

    st.subheader("💰 Potential Monthly Savings: ${:,.2f}".format(total_savings))

    st.subheader("📦 Unattached EBS Volumes")
    if unattached_volumes:
        st.dataframe(pd.DataFrame(unattached_volumes), use_container_width=True)
    else:
        st.info("No unattached volumes found.")

    st.subheader("🔌 Unassociated Elastic IPs")
    if unassociated_eips:
        st.dataframe(pd.DataFrame(unassociated_eips), use_container_width=True)
    else:
        st.info("No unassociated Elastic IPs found.")

    st.subheader("📦 Old Snapshots (>90 days)")
    if old_snapshots:
        st.dataframe(pd.DataFrame(old_snapshots), use_container_width=True)
    else:
        st.info("No old snapshots found.")
