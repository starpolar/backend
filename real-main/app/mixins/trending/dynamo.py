import logging
from decimal import Decimal

import pendulum

from . import exceptions

logger = logging.getLogger()


class TrendingDynamo:

    PERCISION = Decimal(10) ** -9

    def __init__(self, item_type, dynamo_client):
        self.item_type = item_type
        self.client = dynamo_client

    def pk(self, item_id):
        return {
            'partitionKey': f'{self.item_type}/{item_id}',
            'sortKey': 'trending',
        }

    def get(self, item_id, strongly_consistent=False):
        return self.client.get_item(self.pk(item_id), ConsistentRead=strongly_consistent)

    def add(self, item_id, initial_score, now=None):
        assert isinstance(initial_score, Decimal), 'Boto uses decimals for numbers'
        assert initial_score >= 0, 'Score cannot be negative'
        now = now or pendulum.now('utc')
        now_str = now.to_iso8601_string()
        pk = self.pk(item_id)
        query_kwargs = {
            'Item': {
                'partitionKey': pk['partitionKey'],
                'sortKey': pk['sortKey'],
                'schemaVersion': 0,
                'gsiK3PartitionKey': f'{self.item_type}/trending',
                'gsiK3SortKey': initial_score.quantize(self.PERCISION).normalize(),
                'lastDeflatedAt': now_str,
                'createdAt': now_str,
            },
        }
        try:
            return self.client.add_item(query_kwargs)
        except self.client.exceptions.ConditionalCheckFailedException:
            raise exceptions.TrendingAlreadyExists(self.item_type, item_id)

    def add_score(self, item_id, score_to_add, expected_last_deflated_at):
        assert isinstance(score_to_add, Decimal), 'Boto uses decimals for numbers'
        assert score_to_add >= 0, 'Score cannot be negative'
        query_kwargs = {
            'Key': self.pk(item_id),
            'UpdateExpression': 'ADD gsiK3SortKey :sta',
            'ConditionExpression': 'lastDeflatedAt = :elda',
            'ExpressionAttributeValues': {
                ':sta': score_to_add.quantize(self.PERCISION).normalize(),
                ':elda': expected_last_deflated_at.to_iso8601_string(),
            },
        }
        try:
            return self.client.update_item(query_kwargs)
        except self.client.exceptions.ConditionalCheckFailedException:
            raise exceptions.TrendingDNEOrAttributeMismatch(self.item_type, item_id)

    def deflate_score(self, item_id, expected_score, new_score, expected_last_deflation_date, now):
        assert isinstance(expected_score, Decimal), 'Boto uses decimals for numbers'
        assert isinstance(new_score, Decimal), 'Boto uses decimals for numbers'
        assert new_score >= 0, 'Score cannot be negative'
        assert expected_score > new_score, 'New score must be less than existing score'
        query_kwargs = {
            'Key': self.pk(item_id),
            'UpdateExpression': 'SET gsiK3SortKey = :ns, lastDeflatedAt = :lda',
            'ConditionExpression': 'gsiK3SortKey = :es AND begins_with(lastDeflatedAt, :eldd)',
            'ExpressionAttributeValues': {
                ':es': expected_score,  # no normalization because must match exactly
                ':ns': new_score.quantize(self.PERCISION).normalize(),
                ':lda': now.to_iso8601_string(),
                ':eldd': str(expected_last_deflation_date),
            },
        }
        try:
            return self.client.update_item(query_kwargs)
        except self.client.exceptions.ConditionalCheckFailedException:
            raise exceptions.TrendingDNEOrAttributeMismatch(self.item_type, item_id)

    def delete(self, item_id, expected_score=None):
        if expected_score is not None:
            assert isinstance(expected_score, Decimal), 'Boto uses decimals for numbers'
            kwargs = {
                'ConditionExpression': 'gsiK3SortKey = :es',
                'ExpressionAttributeValues': {
                    ':es': expected_score,  # no normalization because must match exactly
                },
            }
        else:
            kwargs = {}
        try:
            return self.client.delete_item(self.pk(item_id), **kwargs)
        except self.client.exceptions.ConditionalCheckFailedException:
            raise exceptions.TrendingDNEOrAttributeMismatch(self.item_type, item_id)

    def generate_keys(self):
        "Generates only primary key and GSI-K3. Ordered with lowest score first."
        query_kwargs = {
            'KeyConditionExpression': 'gsiK3PartitionKey = :gsik3pk',
            'ExpressionAttributeValues': {':gsik3pk': f'{self.item_type}/trending'},
            'IndexName': 'GSI-K3',
        }
        return self.client.generate_all_query(query_kwargs)
