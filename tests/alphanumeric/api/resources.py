from builtins import object
from tastypie.authorization import Authorization
from tastypie.fields import CharField
from tastypie.resources import ModelResource
from alphanumeric.models import Product


class ProductResource(ModelResource):
    class Meta(object):
        resource_name = 'products'
        queryset = Product.objects.all()
        authorization = Authorization()
