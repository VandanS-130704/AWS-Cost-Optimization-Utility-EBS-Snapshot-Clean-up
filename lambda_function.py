import boto3

def lambda_handler(event, context):
    ec2 = boto3.client('ec2')

    # Get all EBS snapshots using a paginator for safety
    active_snapshots = []
    paginator = ec2.get_paginator('describe_snapshots') 
    for page in paginator.paginate(OwnerIds=['self']):
        active_snapshots.extend(page['Snapshots']) 

    # Get all active (running) EC2 instance IDs using a paginator
    active_instance_ids = set()
    paginator = ec2.get_paginator('describe_instances') 
    pages = paginator.paginate(Filters=[{'Name': 'instance-state-name', 'Values': ['running']}]) 

    for page in pages:
        for reservation in page['Reservations']:
            for instance in reservation['Instances']:
                active_instance_ids.add(instance['InstanceId'])

    print(f"Found {len(active_instance_ids)} running instances.")

    # Iterate through each snapshot
    for snapshot in active_snapshots:
        snapshot_id = snapshot['SnapshotId']
        volume_id = snapshot.get('VolumeId')

        if not volume_id:
            # Delete the snapshot if it's not attached to any volume
            ec2.delete_snapshot(SnapshotId=snapshot_id)
            print(f"Deleted EBS snapshot {snapshot_id} as it was not attached to any volume.")
        else:
            # Check if the volume still exists
            try:
                volume_response = ec2.describe_volumes(VolumeIds=[volume_id])
                
                # Check if volume has any attachments
                attachments = volume_response['Volumes'][0].get('Attachments', [])

                if not attachments:
                    # --- This block is for unattached volumes ---
                    ec2.delete_snapshot(SnapshotId=snapshot_id)
                    print(f"Deleted EBS snapshot {snapshot_id} as its volume {volume_id} is not attached to any instance.")
                else:
                    # --- This block checks if attachments are to *running* instances ---
                    attached_to_running = False
                    for attachment in attachments:
                        if attachment['InstanceId'] in active_instance_ids:
                            attached_to_running = True
                            print(f"Keeping snapshot {snapshot_id}. Volume {volume_id} is attached to running instance {attachment['InstanceId']}.")
                            break # Found a running instance, so we keep it
                    
                    if not attached_to_running:
                        # Volume is attached, but only to STOPPED instances
                        ec2.delete_snapshot(SnapshotId=snapshot_id)
                        print(f"Deleted EBS snapshot {snapshot_id} as its volume {volume_id} is attached, but not to any *running* instances.")
                # --- End of changed block ---

            except ec2.exceptions.ClientError as e:
                if e.response['Error']['Code'] == 'InvalidVolume.NotFound':
                    # The volume associated with the snapshot is not found (it might have been deleted)
                    ec2.delete_snapshot(SnapshotId=snapshot_id)
                    print(f"Deleted EBS snapshot {snapshot_id} as its associated volume {volume_id} was not found.")
                else:
                    # Some other error (like permissions)
                    print(f"Could not check volume {volume_id} for snapshot {snapshot_id}: {e}")

    return {
        'statusCode': 200,
        'body': 'Snapshot cleanup finished.'
    }
